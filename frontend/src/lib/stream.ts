import type { InterruptPayload } from "@/types/chat";
import type { ToolResult } from "@/types/tools";

/**
 * NDJSON 流式读取。
 *
 * 后端 /chat/stream 每行推一个完整 JSON（media_type: application/x-ndjson）。
 * Python 客户端靠 httpx 的 aiter_lines() 免费拿到按行切分；浏览器里没有这个
 * 便利——fetch 的 reader 按**网络 chunk** 而不是按行给数据，一个 JSON 行完全
 * 可能被切成两半。所以必须自己缓冲不完整的尾巴。
 *
 * 这段逻辑由 stream.test.ts 覆盖（故意在 JSON 中间切断、末行无换行、单 chunk
 * 含多行三种情况）。
 */

/** 阶段状态提示，如「正在分析问题...」。前端只用它判断流是否还在跑。 */
export interface StatusEvent {
  type: "status";
  data: string;
}

/** 逐 token 的回答文本。 */
export interface ContentEvent {
  type: "content";
  data: string;
}

/** 工具事件。status: "start" 只带 input，"end" 才带 result。 */
export interface ToolEvent {
  type: "tool";
  data: {
    tool: string;
    status: "start" | "end";
    input?: Record<string, unknown>;
    output_preview?: string;
    result?: ToolResult;
  };
}

/**
 * 需要人工确认的暂停点（HITL）。
 *
 * 收到它之后紧接着会来一条 "等待确认" 的 status，然后流就结束了——不会再有
 * content 和 "完成"。所以上层必须把它当成流的终点来处理，而不是过程事件。
 */
export interface InterruptEvent {
  type: "interrupt";
  data: InterruptPayload;
}

export type StreamEvent =
  | StatusEvent
  | ContentEvent
  | ToolEvent
  | InterruptEvent;

/**
 * 把 fetch 响应体逐行解析成事件。
 *
 * @param res - fetch 返回的流式响应，body 不能为空。
 * @yields 每行一个解析好的事件对象。
 */
export async function* readNdjson(res: Response): AsyncGenerator<StreamEvent> {
  if (!res.body) throw new Error("响应没有可读的流式 body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    // stream: true 让多字节字符跨 chunk 边界时也能正确解码（中文一定会遇到）
    buf += decoder.decode(value, { stream: true });

    const lines = buf.split("\n");
    // 最后一段可能是被切断的半行，留到下一轮再拼
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line) as StreamEvent;
    }
  }

  // 收尾：后端最后一行可能不带尾随换行
  if (buf.trim()) yield JSON.parse(buf) as StreamEvent;
}
