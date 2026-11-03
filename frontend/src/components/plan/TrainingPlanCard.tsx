import { ClipboardList, Loader2, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { PlanDays, buildAllSwaps } from "@/components/plan/PlanDays";
import type { PlanSwaps } from "@/components/plan/PlanDays";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { PlanSwap, TrainingPlan } from "@/types/plan";

const SPLIT_LABEL: Record<string, string> = {
  three_day: "三分化",
  five_day: "五分化",
};

const EXPERIENCE_LABEL: Record<string, string> = {
  beginner: "新手",
  experienced: "有经验",
};

/** 计划结果卡：人体图生成/历史计划用可编辑版，聊天工具结果用只读版。 */
export function TrainingPlanCard({
  plan,
  onSave,
  saving = false,
  onDelete,
  deleting = false,
}: {
  plan: TrainingPlan;
  /** 传入后允许逐个换动作并保存；不传就是只读。 */
  onSave?: (swaps: PlanSwap[]) => Promise<void> | void;
  saving?: boolean;
  /** 传入后在卡片右上角显示删除按钮（两次点击确认）。 */
  onDelete?: () => Promise<void> | void;
  deleting?: boolean;
}) {
  const [swaps, setSwaps] = useState<PlanSwaps>({});
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    setSwaps({});
    setError(null);
    setConfirmDelete(false);
  }, [plan.plan_id]);

  useEffect(() => {
    if (!confirmDelete) return;
    const timer = window.setTimeout(() => setConfirmDelete(false), 4000);
    return () => window.clearTimeout(timer);
  }, [confirmDelete]);

  const changed = Object.keys(swaps).length > 0;
  const sourceLabel = plan.source === "chat" ? "AI 对话生成" : "人体图生成";

  async function save() {
    if (!onSave || saving) return;
    setError(null);
    try {
      await onSave(buildAllSwaps(plan, swaps));
      setSwaps({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function remove() {
    if (!onDelete || deleting) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setConfirmDelete(false);
    void onDelete();
  }

  return (
    <Card className="border-brand/30">
      <CardHeader
        icon={<ClipboardList />}
        title={plan.name}
        subtitle={`${SPLIT_LABEL[plan.split] ?? plan.split} · ${
          EXPERIENCE_LABEL[plan.experience] ?? plan.experience
        } · ${plan.goal}`}
        action={
          <div className="flex items-center gap-1.5">
            <span className="rounded-full bg-brand-soft px-2.5 py-1 text-xs text-brand">
              {sourceLabel}
            </span>
            {onDelete ? (
              <div className="flex items-center gap-1">
                {confirmDelete ? (
                  <span className="text-[11px] text-delta-down">
                    再点一次删除
                  </span>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className={
                    confirmDelete
                      ? "size-7 text-delta-down"
                      : "size-7 text-ink-muted"
                  }
                  disabled={deleting}
                  title={confirmDelete ? "再次点击确认删除" : "删除计划"}
                  aria-label={confirmDelete ? "再次点击确认删除计划" : "删除计划"}
                  onClick={() => remove()}
                >
                  {deleting ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Trash2 />
                  )}
                </Button>
                {confirmDelete ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    title="取消删除"
                    aria-label="取消删除"
                    onClick={() => setConfirmDelete(false)}
                  >
                    ×
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        }
      />
      <CardBody className="space-y-3">
        <PlanDays
          plan={plan}
          swaps={swaps}
          disabled={saving}
          onSwap={
            onSave
              ? (slotId, exerciseName) =>
                  setSwaps((prev) => ({ ...prev, [slotId]: exerciseName }))
              : undefined
          }
        />

        {plan.warnings.length > 0 ? (
          <div className="rounded-lg border border-brand/30 bg-brand-soft/40 px-2.5 py-1.5 text-xs text-ink-2">
            {plan.warnings.join(" ")}
          </div>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-delta-down/40 bg-delta-down/5 px-2.5 py-1.5 text-xs text-ink">
            {error}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-hairline pt-2">
          <span className="text-xs text-ink-muted">
            已保存 · {new Date(plan.created_at).toLocaleString("zh-CN")}
          </span>
          {onSave ? (
            <Button
              size="sm"
              variant="outline"
              disabled={!changed || saving}
              onClick={() => void save()}
            >
              {saving ? <Loader2 className="animate-spin" /> : <Save />}
              {saving ? "保存中…" : "保存修改"}
            </Button>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}
