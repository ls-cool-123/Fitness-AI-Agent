import { AlertTriangle, Dumbbell, Plus, Send, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { MessageList } from "@/components/chat/MessageList";
import type { UiConfirmation, UiMessage } from "@/components/chat/MessageList";
import { Button } from "@/components/ui/button";
import { chatStream, confirmChat, ConfirmConflictError } from "@/lib/api";
import { isConfirmPlanInterrupt, isConfirmWorkoutInterrupt } from "@/types/chat";
import type { ConfirmEditPayload } from "@/types/chat";

const SUGGESTIONS = [
  "帮我制定训练计划",
  "我最近练了什么？",
  "深蹲有进步吗？",
  "这个月背部练了多少？",
  "卧推的正确姿势是什么？",
];

/**
 * 会话 id 由前端生成，后端只拿它拼 thread_id，不校验格式。
 *
 * randomUUID 需要安全上下文（https 或 localhost）；内网用 http 打开时降级成
 * 时间戳 + 随机串，保证「新对话」在任何部署方式下都还能用。
 */
function createConversationId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `conv-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * 有确认卡片挂起时不要再往 Agent 发消息。
 *
 * LangGraph 线程停在 interrupt() 上，必须用 /chat/confirm 恢复；此时再发普通
 * 聊天消息会让 Agent 收不到可执行输入，界面就一直「思考中」。所以先在前端
 * 拦住，并指引用户去卡片里操作（换动作/确认/取消）。
 */
function pendingConfirmationHint(messages: UiMessage[]): string | null {
  const pending = [...messages]
    .reverse()
    .find(
      (msg) =>
        msg.confirmation &&
        (msg.confirmation.status === "pending" ||
          msg.confirmation.status === "submitting"),
    );
  if (!pending?.confirmation) return null;
  if (pending.confirmation.status === "submitting") {
    return "正在提交上一次确认，请稍候；不要在确认完成前继续发消息。";
  }
  return pending.confirmation.value.action === "confirm_plan"
    ? "当前有一个待确认的训练计划。请在上方的计划卡片中直接下拉替换动作，或点「取消」后再重新生成；确认前不需要在对话里告诉我换哪个动作。"
    : "当前有一个待确认的训练记录。请先在上方卡片里确认或取消，再继续对话。";
}

function Welcome({
  onPick,
  onOpenPlan,
}: {
  onPick: (text: string) => void;
  onOpenPlan?: () => void;
}) {
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
      {onOpenPlan ? (
        <button
          type="button"
          onClick={onOpenPlan}
          className="mt-4 text-xs text-ink-muted underline-offset-4 transition-colors hover:text-brand hover:underline"
        >
          不想聊天？直接去人体图点肌肉选动作 →
        </button>
      ) : null}
    </div>
  );
}

export function ChatPanel({
  userId,
  onOpenPlan,
}: {
  userId: string;
  onOpenPlan?: () => void;
}) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState(createConversationId);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // 与 state 同步的会话 id。异步回调（流式循环、confirm 请求）返回时用它判断
  // 会话是否已经被「新对话」换掉，避免把旧会话的结果写进新列表。
  const conversationRef = useRef(conversationId);

  // 确认请求的同步锁：按钮 disabled 要等一次渲染才生效，双击仍可能进两个请求。
  const confirmLockRef = useRef(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streaming]);

  /** 只改最后一条（助手）消息，其余保持引用不变。 */
  function patchLast(patch: (msg: UiMessage) => UiMessage) {
    setMessages((prev) =>
      prev.map((msg, i) => (i === prev.length - 1 ? patch(msg) : msg)),
    );
  }

  /** 按索引改一条消息上的确认卡片状态，不影响消息正文和工具结果。 */
  function patchConfirmation(
    index: number,
    patch: (confirmation: UiConfirmation) => UiConfirmation,
  ) {
    setMessages((prev) =>
      prev.map((msg, i) => {
        if (i !== index || !msg.confirmation) return msg;
        return { ...msg, confirmation: patch(msg.confirmation) };
      }),
    );
  }

  /**
   * 新对话：换一个 conversation_id 就是后端的新线程，旧历史留在旧线程里。
   * 先中断进行中的流，否则它的后续事件会继续往清空后的列表里塞内容。
   */
  function startNewConversation() {
    abortRef.current?.abort();
    abortRef.current = null;
    const next = createConversationId();
    conversationRef.current = next;
    setConversationId(next);
    setMessages([]);
    setInput("");
    setError(null);
    // 旧流的 finally 会因为会话已切换而跳过收尾，这里必须自己复位
    setStreaming(false);
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || streaming) return;

    const pendingHint = pendingConfirmationHint(messages);
    if (pendingHint) {
      setMessages([
        ...messages,
        { role: "user", content: question },
        { role: "assistant", content: pendingHint },
      ]);
      setInput("");
      setError(null);
      return;
    }

    // 发给后端的是全量历史 + 这条新消息（不含占位的空助手消息）。
    // 为什么要全量：见 lib/api.ts 里 chatStream 的说明。
    const history = messages.map(({ role, content }) => ({ role, content }));
    const payload = [...history, { role: "user" as const, content: question }];

    // 会话在请求期间可能被「新对话」换掉，捕获这次请求所属的线程用于回写判断
    const threadAtStart = conversationRef.current;

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
        conversationId: threadAtStart,
        signal: controller.signal,
      })) {
        if (conversationRef.current !== threadAtStart) break;

        if (event.type === "content") {
          patchLast((msg) => ({ ...msg, content: msg.content + event.data }));
        } else if (event.type === "tool" && event.data.status === "end") {
          const outcome = {
            tool: event.data.tool,
            result: event.data.result ?? null,
          };
          patchLast((msg) => ({
            ...msg,
            results: [...(msg.results ?? []), outcome],
          }));
        } else if (event.type === "interrupt") {
          // 只认结构完整的 confirm_workout / confirm_plan；未知 action 直接忽略，
          // 宁可不出卡片也不能让一次不认识的中断把整个消息列表渲染崩掉。
          if (
            !isConfirmWorkoutInterrupt(event.data) &&
            !isConfirmPlanInterrupt(event.data)
          ) {
            continue;
          }
          const { id, value } = event.data;
          patchLast((msg) => ({
            ...msg,
            confirmation: { id, value, status: "pending", error: null },
          }));
        }
        // status 事件刻意忽略：它带的是「正在调用 xx 工具」这类过程文案
      }
    } catch (err) {
      if (controller.signal.aborted) {
        if (conversationRef.current === threadAtStart) {
          patchLast((msg) => ({
            ...msg,
            content: msg.content || "（已停止）",
          }));
        }
      } else {
        // 会话已切换时，旧请求的失败与新会话无关，不要在新页面弹错误条
        if (conversationRef.current === threadAtStart) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    } finally {
      // 会话已被换掉时不能污染新会话的状态（新流可能已经把它置为 true / 新 controller）
      if (conversationRef.current === threadAtStart) {
        setStreaming(false);
        abortRef.current = null;
      }
    }
  }

  /**
   * 确认 / 取消挂起的写入。
   *
   * 409 是「线程里没有待确认操作」的正常业务分支，卡片进入失效终态即可；
   * 其余错误保留卡片可操作，让用户能重试。
   */
  async function respondToConfirmation(
    messageIndex: number,
    approved: boolean,
    edits?: ConfirmEditPayload[],
  ) {
    if (confirmLockRef.current) return;
    const current = messages[messageIndex]?.confirmation;
    if (!current || current.status !== "pending") return;

    confirmLockRef.current = true;
    const threadAtStart = conversationRef.current;

    patchConfirmation(messageIndex, (confirmation) => ({
      ...confirmation,
      status: "submitting",
      error: null,
    }));

    try {
      const res = await confirmChat({
        userId,
        conversationId: threadAtStart,
        approved,
        edits,
      });

      // 请求期间用户可能点了「新对话」，旧结果不能再落到新会话里
      if (conversationRef.current !== threadAtStart) return;

      patchConfirmation(messageIndex, (confirmation) => ({
        ...confirmation,
        status: approved ? "confirmed" : "cancelled",
        error: null,
      }));

      // 恢复执行后 Agent 的总结作为新的一条助手消息追加；卡片本身只留终态。
      // answer 为空时不追加，避免在列表末尾留下一个只有头像的空消息。
      if (res.answer.trim()) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: res.answer },
        ]);
      }
    } catch (err) {
      if (conversationRef.current !== threadAtStart) return;

      if (err instanceof ConfirmConflictError) {
        patchConfirmation(messageIndex, (confirmation) => ({
          ...confirmation,
          status: "expired",
          error: null,
        }));
      } else {
        patchConfirmation(messageIndex, (confirmation) => ({
          ...confirmation,
          status: "pending",
          error: err instanceof Error ? err.message : String(err),
        }));
      }
    } finally {
      confirmLockRef.current = false;
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex justify-end border-b border-hairline py-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={startNewConversation}
        >
          <Plus />
          新对话
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1 py-4">
        {messages.length === 0 ? (
          <Welcome onPick={send} onOpenPlan={onOpenPlan} />
        ) : (
          <MessageList
            messages={messages}
            streaming={streaming}
            onConfirm={(messageIndex, edits) =>
              respondToConfirmation(messageIndex, true, edits)
            }
            onCancel={(messageIndex) =>
              respondToConfirmation(messageIndex, false)
            }
          />
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
            // 中文输入法组合期间按 Enter 是「选字」，不能当成发送；
            // 同时用 textarea 当前值而不是闭包里的 input，避免 IME 下
            // state 还没同步、发送了空字符串。
            if (e.key !== "Enter" || e.shiftKey) return;
            if (e.nativeEvent.isComposing) return;
            e.preventDefault();
            if (!streaming) void send(e.currentTarget.value);
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
