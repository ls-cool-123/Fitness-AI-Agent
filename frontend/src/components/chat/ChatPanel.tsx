import { AlertTriangle, Dumbbell, Send, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { MessageList } from "@/components/chat/MessageList";
import type { ToolOutcome, UiMessage } from "@/components/chat/MessageList";
import { Button } from "@/components/ui/button";
import { chatStream } from "@/lib/api";

const SUGGESTIONS = [
  "我最近练了什么？",
  "深蹲有进步吗？",
  "这个月背部练了多少？",
  "卧推的正确姿势是什么？",
];

function Welcome({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="py-10 text-center">
      <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-brand to-brand-strong text-brand-ink shadow-lg">
        <Dumbbell className="size-7" />
      </span>
      <h2 className="mt-4 text-lg font-semibold text-ink">今天想练什么？</h2>
      <p className="mt-1 text-sm text-ink-2">
        问我训练计划、动作要领，或者查你自己的训练数据
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((text) => (
          <button
            key={text}
            type="button"
            onClick={() => onPick(text)}
            className="rounded-full border border-hairline bg-card px-3.5 py-1.5 text-sm text-ink-2 transition-colors hover:border-brand hover:text-brand"
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ChatPanel({ userId }: { userId: string }) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streaming]);

  /** 只改最后一条（助手）消息，其余保持引用不变。 */
  function patchLast(patch: (msg: UiMessage) => UiMessage) {
    setMessages((prev) =>
      prev.map((msg, i) => (i === prev.length - 1 ? patch(msg) : msg)),
    );
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || streaming) return;

    // 发给后端的是全量历史 + 这条新消息（不含占位的空助手消息）。
    // 为什么要全量：见 lib/api.ts 里 chatStream 的说明。
    const history = messages.map(({ role, content }) => ({ role, content }));
    const payload = [...history, { role: "user" as const, content: question }];

    setMessages([
      ...messages,
      { role: "user", content: question },
      { role: "assistant", content: "", results: [] },
    ]);
    setInput("");
    setError(null);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const event of chatStream({
        messages: payload,
        userId,
        signal: controller.signal,
      })) {
        if (event.type === "content") {
          patchLast((msg) => ({ ...msg, content: msg.content + event.data }));
        } else if (event.type === "tool" && event.data.status === "end") {
          const outcome: ToolOutcome = {
            tool: event.data.tool,
            result: event.data.result ?? null,
          };
          patchLast((msg) => ({
            ...msg,
            results: [...(msg.results ?? []), outcome],
          }));
        }
        // status 事件刻意忽略：它带的是「正在调用 xx 工具」这类过程文案
      }
    } catch (err) {
      if (controller.signal.aborted) {
        patchLast((msg) => ({
          ...msg,
          content: msg.content || "（已停止）",
        }));
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-1 py-4">
        {messages.length === 0 ? (
          <Welcome onPick={send} />
        ) : (
          <MessageList messages={messages} streaming={streaming} />
        )}

        {error ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-delta-down/40 bg-delta-down/5 px-3 py-2.5 text-sm text-ink">
            <AlertTriangle
              className="mt-0.5 size-4 shrink-0 text-delta-down"
              aria-hidden="true"
            />
            <div>
              <div className="font-medium">请求失败</div>
              <div className="mt-0.5 text-xs text-ink-2">{error}</div>
            </div>
          </div>
        ) : null}

        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="flex items-end gap-2 border-t border-hairline bg-card/60 px-1 pt-3 pb-1"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(input);
            }
          }}
          rows={1}
          placeholder="问点什么…（Enter 发送，Shift+Enter 换行）"
          className="max-h-32 min-h-9 flex-1 resize-none rounded-xl border border-hairline bg-page px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-ink-muted focus:border-brand focus:ring-2 focus:ring-brand/30"
        />
        {streaming ? (
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-9"
            onClick={() => abortRef.current?.abort()}
            aria-label="停止生成"
          >
            <Square className="size-4" />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            className="size-9"
            disabled={!input.trim()}
            aria-label="发送"
          >
            <Send className="size-4" />
          </Button>
        )}
      </form>
    </div>
  );
}
