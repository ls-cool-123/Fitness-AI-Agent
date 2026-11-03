import { describe, expect, it } from "vitest";

import { isConfirmWorkoutInterrupt } from "@/types/chat";
import { readNdjson } from "./stream";
import type { StreamEvent } from "./stream";

/** 把若干字符串片段包成一个只读 body 的假 Response。 */
function responseFromChunks(chunks: string[]): Response {
  const encoder = new TextEncoder();
  let i = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i++]));
      } else {
        controller.close();
      }
    },
  });
  return new Response(body);
}

async function collect(chunks: string[]): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const ev of readNdjson(responseFromChunks(chunks))) out.push(ev);
  return out;
}

describe("readNdjson", () => {
  it("拼回被 chunk 边界切断的 JSON 行", async () => {
    const events = await collect([
      '{"type":"cont',
      'ent","data":"你"}\n{"type":"content","da',
      'ta":"好"}\n',
    ]);

    expect(events).toEqual([
      { type: "content", data: "你" },
      { type: "content", data: "好" },
    ]);
  });

  it("末行不带尾随换行时也能产出", async () => {
    const events = await collect(['{"type":"status","data":"完成"}']);
    expect(events).toEqual([{ type: "status", data: "完成" }]);
  });

  it("单个 chunk 里含多行时全部产出", async () => {
    const events = await collect([
      '{"type":"status","data":"a"}\n{"type":"status","data":"b"}\n{"type":"status","data":"c"}\n',
    ]);
    expect(events.map((e) => e.data)).toEqual(["a", "b", "c"]);
  });

  it("跳过空行，不因此抛异常", async () => {
    const events = await collect(['{"type":"content","data":"x"}\n\n\n']);
    expect(events).toHaveLength(1);
  });

  it("多字节字符被切断在两个 chunk 之间也能正确解码", async () => {
    // 「深」的 UTF-8 是 3 字节，这里刻意在第 2 字节后切断
    const encoder = new TextEncoder();
    const full = encoder.encode('{"type":"content","data":"深蹲"}\n');
    const cut = 27; // 落在「深」的字节中间
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(full.slice(0, cut));
        controller.enqueue(full.slice(cut));
        controller.close();
      },
    });

    const out: StreamEvent[] = [];
    for await (const ev of readNdjson(new Response(body))) out.push(ev);

    expect(out).toEqual([{ type: "content", data: "深蹲" }]);
  });

  it("保留 tool 事件里的完整 result", async () => {
    const line = JSON.stringify({
      type: "tool",
      data: {
        tool: "analyze_progress_tool",
        status: "end",
        result: { exercise: "深蹲", trend_direction: "up" },
      },
    });
    const events = await collect([line + "\n"]);

    expect(events[0]).toMatchObject({
      type: "tool",
      data: { tool: "analyze_progress_tool", status: "end" },
    });
  });

  it("解析 interrupt 事件，并交给可用的类型守卫", async () => {
    const interrupt = {
      type: "interrupt",
      data: {
        id: "int-1",
        value: {
          action: "confirm_workout",
          message: "即将写入训练记录，请确认解析结果",
          preview: [
            {
              name: "深蹲",
              sets: 5,
              reps: 5,
              weight_kg: 80,
              set_details: null,
              notes: null,
            },
          ],
        },
        thread_id: "u-1:abc",
      },
    };

    // 真实流里 interrupt 之后紧跟一条「等待确认」，然后直接结束
    const events = await collect([
      JSON.stringify(interrupt) + "\n",
      '{"type":"status","data":"等待确认"}\n',
    ]);

    expect(events.map((event) => event.type)).toEqual(["interrupt", "status"]);

    const [event] = events;
    if (event.type !== "interrupt") throw new Error("期望 interrupt 事件");
    expect(event.data.thread_id).toBe("u-1:abc");
    expect(isConfirmWorkoutInterrupt(event.data)).toBe(true);
  });
});
