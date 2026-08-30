import { Dumbbell } from "lucide-react";

import { ToolResultCard } from "@/components/chat/results";
import type { ToolResult } from "@/types/tools";

/** 一条工具结果，按到达顺序挂在对应的助手消息上。 */
export interface ToolOutcome {
  tool: string;
  result: ToolResult;
}

/**
 * 界面上的一条消息。
 *
 * 比发给后端的 ChatMessage 多了 `results` —— 工具结果只活在前端，不进对话历史
 * （后端自己有 checkpointer，把卡片数据回传给它没有意义还会撑大 payload）。
 */
export interface UiMessage {
  role: "user" | "assistant";
  content: string;
  results?: ToolOutcome[];
}

function Avatar() {
  return (
    <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand to-brand-strong text-brand-ink shadow-sm">
      <Dumbbell className="size-4" />
    </span>
  );
}

/** 流式期间的通用指示器 —— 只说「在想」，不报工具名（刻意不暴露调用过程）。 */
function Thinking() {
  return (
    <div className="flex items-center gap-1.5 text-sm text-ink-muted">
      <Dumbbell className="size-4 animate-bounce text-brand" aria-hidden="true" />
      <span>思考中</span>
      <span className="inline-flex gap-0.5">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="size-1 animate-pulse rounded-full bg-brand"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
    </div>
  );
}

export function MessageList({
  messages,
  streaming,
}: {
  messages: UiMessage[];
  /** 最后一条助手消息是否还在生成中 */
  streaming: boolean;
}) {
  return (
    <div className="space-y-5">
      {messages.map((msg, i) => {
        const last = i === messages.length - 1;

        if (msg.role === "user") {
          return (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-brand to-brand-strong px-4 py-2.5 text-sm whitespace-pre-wrap text-brand-ink shadow-sm">
                {msg.content}
              </div>
            </div>
          );
        }

        return (
          <div key={i} className="flex gap-3">
            <Avatar />
            <div className="min-w-0 flex-1 space-y-3">
              {msg.content ? (
                <div className="text-sm leading-relaxed whitespace-pre-wrap text-ink">
                  {msg.content}
                </div>
              ) : null}

              {msg.results?.map((outcome, j) => (
                <ToolResultCard
                  key={`${outcome.tool}-${j}`}
                  tool={outcome.tool}
                  result={outcome.result}
                />
              ))}

              {last && streaming && !msg.content ? <Thinking /> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
