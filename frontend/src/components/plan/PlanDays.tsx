import { Flame, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import type { PlanEdit } from "@/types/chat";
import type { PlanPreview, PlanSwap } from "@/types/plan";

/** 当前每个 slot 的选择；没有改过的 slot 不在 map 里。 */
export type PlanSwaps = Record<string, string>;

function slotName(slotId: string, original: string, swaps: PlanSwaps): string {
  return swaps[slotId] ?? original;
}

/**
 * 计划正文（每天 + 动作）。确认卡片、结果卡片、历史计划共用。
 *
 * 传入 `onSwap` 时每个动作变成下拉；选项里禁用已经被其他 slot 选走的动作，
 * 避免用户在 UI 上先造出一个后端必然拒绝的重复状态。传入 `onRemove` 时
 * 每行右侧出现删除按钮（至少保留每天一个动作，避免生成空训练日）。
 */
export function PlanDays({
  plan,
  swaps,
  onSwap,
  onRemove,
  removed,
  disabled = false,
}: {
  plan: PlanPreview;
  swaps: PlanSwaps;
  onSwap?: (slotId: string, exerciseName: string) => void;
  onRemove?: (slotId: string) => void;
  removed?: ReadonlySet<string>;
  disabled?: boolean;
}) {
  const selectedNames = new Set(
    plan.days.flatMap((day) =>
      day.exercises
        .filter((slot) => !removed?.has(slot.slot_id))
        .map((slot) => slotName(slot.slot_id, slot.name, swaps)),
    ),
  );

  return (
    <div className="space-y-3">
      {plan.days.map((day) => {
        const visible = day.exercises.filter(
          (slot) => !removed?.has(slot.slot_id),
        );
        const canRemove = visible.length > 1;
        return (
          <div
            key={day.day}
            className="rounded-lg border border-hairline bg-page px-3 py-2.5"
          >
            <div className="mb-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="text-sm font-semibold text-ink">
                第 {day.day} 天 · {day.title}
              </span>
              <span className="text-xs text-ink-muted">
                {day.focus.join(" / ")}
              </span>
            </div>
            <div className="mb-2 text-xs text-ink-muted">{day.warmup}</div>

            <div className="space-y-1.5">
              {visible.map((slot) => {
                const current = slotName(slot.slot_id, slot.name, swaps);
                const options = [slot.name, ...slot.alternatives].filter(
                  (name, index, arr) => arr.indexOf(name) === index,
                );
                return (
                  <div
                    key={slot.slot_id}
                    className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-hairline bg-card px-2.5 py-1.5"
                  >
                    {onSwap ? (
                      <Select
                        aria-label={`${day.title} 第 ${slot.slot_id} 个动作`}
                        className="h-8 min-w-0 flex-1 px-2 text-sm"
                        value={current}
                        disabled={disabled}
                        onChange={(event) =>
                          onSwap(slot.slot_id, event.target.value)
                        }
                      >
                        {options.map((name) => (
                          <option
                            key={name}
                            value={name}
                            disabled={name !== current && selectedNames.has(name)}
                          >
                            {name}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <span className="min-w-0 flex-1 truncate text-sm text-ink">
                        {current}
                      </span>
                    )}
                    <span className="shrink-0 text-xs text-ink-2 tabular">
                      {slot.sets} 组 × {slot.reps}
                    </span>
                    <span className="shrink-0 text-xs text-ink-muted tabular">
                      休息 {slot.rest_seconds}s
                    </span>
                    {onRemove ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-7 shrink-0 text-ink-muted hover:text-delta-down"
                        disabled={disabled || !canRemove}
                        title={
                          canRemove
                            ? `删除 ${current}`
                            : "每天至少保留一个动作"
                        }
                        aria-label={`删除 ${current}`}
                        onClick={() => onRemove(slot.slot_id)}
                      >
                        <Trash2 />
                      </Button>
                    ) : null}
                  </div>
                );
              })}
            </div>

            {visible.some((slot) => slot.note) ? (
              <div className="mt-1.5 flex items-center gap-1 text-xs text-ink-muted">
                <Flame className="size-3" aria-hidden="true" />
                {visible.find((slot) => slot.note)?.note}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/** 把当前 UI 的所有 slot 选择组装成 PATCH/resume 需要的换动作列表。 */
export function buildAllSwaps(plan: PlanPreview, swaps: PlanSwaps): PlanSwap[] {
  return plan.days.flatMap((day) =>
    day.exercises.map((slot) => ({
      slot_id: slot.slot_id,
      exercise_name: slotName(slot.slot_id, slot.name, swaps),
    })),
  );
}

/** 确认卡片用：保留的 slot 回传动作名，被删除的 slot 回传 remove=true。 */
export function buildPlanEdits(
  plan: PlanPreview,
  swaps: PlanSwaps,
  removed: ReadonlySet<string>,
): PlanEdit[] {
  return plan.days.flatMap((day) =>
    day.exercises.map((slot) =>
      removed.has(slot.slot_id)
        ? { slot_id: slot.slot_id, remove: true }
        : {
            slot_id: slot.slot_id,
            exercise_name: slotName(slot.slot_id, slot.name, swaps),
          },
    ),
  );
}
