import {
  CircleCheck,
  CircleX,
  ClipboardCheck,
  Clock,
  Loader2,
} from "lucide-react";
import { useState } from "react";

import { PlanDays, buildPlanEdits } from "@/components/plan/PlanDays";
import type { PlanSwaps } from "@/components/plan/PlanDays";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type {
  ConfirmPlanInterruptValue,
  ConfirmStatus,
  PlanEdit,
} from "@/types/chat";

const TERMINAL_TEXT: Record<"confirmed" | "cancelled" | "expired", string> = {
  confirmed: "已确认，训练计划已保存",
  cancelled: "已取消，本次没有保存计划",
  expired: "该操作已处理或已过期",
};

function terminalText(status: ConfirmStatus, isUpdate: boolean): string | null {
  if (status === "confirmed") {
    return isUpdate ? "已确认，训练计划已更新" : TERMINAL_TEXT.confirmed;
  }
  if (status === "cancelled") return TERMINAL_TEXT.cancelled;
  if (status === "expired") return TERMINAL_TEXT.expired;
  return null;
}

const SPLIT_LABEL: Record<string, string> = {
  three_day: "三分化",
  five_day: "五分化",
};

const EXPERIENCE_LABEL: Record<string, string> = {
  beginner: "新手",
  experienced: "有经验",
};

/** 训练计划的 HITL 确认卡片：确认前可逐个换动作。 */
export function PlanConfirmCard({
  request,
  status,
  error,
  onConfirm,
  onCancel,
}: {
  request: ConfirmPlanInterruptValue;
  status: ConfirmStatus;
  error: string | null;
  onConfirm: (edits: PlanEdit[]) => Promise<void> | void;
  onCancel: () => Promise<void> | void;
}) {
  const [swaps, setSwaps] = useState<PlanSwaps>({});
  const [removed, setRemoved] = useState<Set<string>>(() => new Set());
  const [submittingAction, setSubmittingAction] = useState<
    "confirm" | "cancel" | null
  >(null);

  const busy = status === "submitting" || submittingAction !== null;
  const isUpdate = request.mode === "update";
  const finalText = terminalText(status, isUpdate);
  const terminal = finalText !== null;
  // 只有确认成功时展示用户改过的值/删除；取消/失效回退到原计划
  const displaySwaps =
    terminal && status !== "confirmed" ? {} : swaps;
  const displayRemoved =
    terminal && status !== "confirmed" ? new Set<string>() : removed;

  async function submit(action: "confirm" | "cancel") {
    if (busy) return;
    setSubmittingAction(action);
    try {
      if (action === "confirm") {
        await onConfirm(buildPlanEdits(request.plan, swaps, removed));
      } else {
        await onCancel();
      }
    } finally {
      setSubmittingAction(null);
    }
  }

  const header = (() => {
    if (status === "confirmed") {
      return {
        icon: <CircleCheck />,
        title: "已确认",
        subtitle: isUpdate ? "训练计划已更新" : "训练计划已保存",
      };
    }
    if (status === "cancelled") {
      return {
        icon: <CircleX />,
        title: "已取消",
        subtitle: isUpdate ? "本次没有修改计划" : "本次没有保存计划",
      };
    }
    if (status === "expired") {
      return {
        icon: <Clock />,
        title: "已失效",
        subtitle: "该操作已处理或已过期",
      };
    }
    return {
      icon: <ClipboardCheck />,
      title: isUpdate ? "待确认的计划修改" : "待确认的训练计划",
      subtitle: request.message,
    };
  })();

  return (
    <Card className={terminal ? undefined : "border-brand/40"}>
      <CardHeader {...header} />
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-brand">
            {SPLIT_LABEL[request.plan.split] ?? request.plan.split}
          </span>
          <span className="rounded-full bg-page px-2.5 py-1">
            {EXPERIENCE_LABEL[request.plan.experience] ?? request.plan.experience}
          </span>
          <span>{request.plan.name}</span>
        </div>

        <div className="max-h-[30rem] overflow-y-auto pr-1">
          <PlanDays
            plan={request.plan}
            swaps={displaySwaps}
            removed={displayRemoved}
            disabled={busy || terminal}
            onSwap={
              busy || terminal
                ? undefined
                : (slotId, exerciseName) =>
                    setSwaps((prev) => ({ ...prev, [slotId]: exerciseName }))
            }
            onRemove={
              busy || terminal
                ? undefined
                : (slotId) =>
                    setRemoved((prev) => {
                      const next = new Set(prev);
                      next.add(slotId);
                      return next;
                    })
            }
          />
        </div>

        {displayRemoved.size > 0 ? (
          <div className="text-xs text-ink-muted">
            已移除 {displayRemoved.size} 个动作
            {terminal ? "" : "（确认后生效）"}
          </div>
        ) : null}

        {request.plan.warnings.length > 0 ? (
          <div className="rounded-lg border border-brand/30 bg-brand-soft/40 px-2.5 py-1.5 text-xs text-ink-2">
            {request.plan.warnings.join(" ")}
          </div>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-delta-down/40 bg-delta-down/5 px-2.5 py-1.5 text-xs text-ink">
            {error}
          </div>
        ) : null}

        {finalText !== null ? (
          <div
            className={
              status === "confirmed"
                ? "flex items-center gap-1.5 text-xs text-delta-up"
                : "flex items-center gap-1.5 text-xs text-ink-2"
            }
          >
            {status === "confirmed" ? (
              <CircleCheck className="size-3.5" aria-hidden="true" />
            ) : status === "cancelled" ? (
              <CircleX className="size-3.5" aria-hidden="true" />
            ) : (
              <Clock className="size-3.5" aria-hidden="true" />
            )}
            <span>{finalText}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void submit("confirm")}
            >
              {submittingAction === "confirm" ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {submittingAction === "confirm"
                ? isUpdate
                  ? "更新中…"
                  : "生成中…"
                : isUpdate
                  ? "确认修改"
                  : "确认生成"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => void submit("cancel")}
            >
              {submittingAction === "cancel" ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {submittingAction === "cancel" ? "取消中…" : "取消"}
            </Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
