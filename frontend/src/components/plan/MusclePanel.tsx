import { Check, Dumbbell, Plus, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Experience, PlanMuscleGroup, Split } from "@/types/plan";

const SPLITS: { value: Split; title: string; hint: string }[] = [
  { value: "three_day", title: "三分化", hint: "推 / 拉 / 腿，每周 3 天" },
  { value: "five_day", title: "五分化", hint: "胸 / 背 / 肩 / 手臂 / 腿，每周 5 天" },
];

/** 右侧动作面板：肌群信息 + 新手/老手动作 + 分化选择 + 生成按钮。 */
export function MusclePanel({
  group,
  level,
  onLevelChange,
  split,
  onSplitChange,
  preferred,
  onToggleExercise,
  onGenerate,
  generating,
  error,
}: {
  group: PlanMuscleGroup | null;
  level: Experience;
  onLevelChange: (level: Experience) => void;
  split: Split;
  onSplitChange: (split: Split) => void;
  preferred: string[];
  onToggleExercise: (name: string) => void;
  onGenerate: () => void;
  generating: boolean;
  error: string | null;
}) {
  const exercises = group?.exercises[level] ?? [];

  if (!group) {
    return (
      <div className="flex h-full min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-hairline px-6 text-center">
        <Dumbbell className="size-7 text-brand" aria-hidden="true" />
        <p className="mt-3 text-sm font-medium text-ink">先选一个肌肉部位</p>
        <p className="mt-1 text-xs text-ink-2">
          点击左边人体上的肌肉，或上方肌群按钮。镜头会聚焦，动作会出现在这里。
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-hairline bg-card">
      <div className="border-b border-hairline px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink">{group.name}</h3>
          <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[11px] text-brand">
            {level === "beginner" ? "新手动作" : "老手动作"}
          </span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-ink-2">
          {group.description}
        </p>
      </div>

      <div className="border-b border-hairline px-3 py-2">
        <div className="flex rounded-lg border border-hairline bg-page p-0.5">
          {(["beginner", "experienced"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onLevelChange(value)}
              className={
                level === value
                  ? "flex-1 rounded-md bg-brand px-2 py-1 text-xs font-medium text-brand-ink"
                  : "flex-1 rounded-md px-2 py-1 text-xs text-ink-2 hover:text-brand"
              }
            >
              {value === "beginner" ? "新手" : "老手"}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-3 py-2">
        {exercises.map((exercise) => {
          const selected = preferred.includes(exercise.name);
          return (
            <div
              key={exercise.name}
              className={
                selected
                  ? "rounded-lg border border-brand/50 bg-brand-soft/50 px-2.5 py-2"
                  : "rounded-lg border border-hairline bg-page px-2.5 py-2"
              }
            >
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className="text-sm font-medium text-ink">
                      {exercise.name}
                    </span>
                    <span className="text-[11px] text-ink-muted">
                      {exercise.equipment}
                      {exercise.is_compound ? " · 复合" : " · 孤立"}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-muted">
                    参考 {exercise.default_sets} 组 × {exercise.default_reps} ·
                    休息 {exercise.rest_seconds}s
                  </div>
                  <p className="mt-0.5 text-xs leading-relaxed text-ink-2">
                    {exercise.description}
                  </p>
                </div>
                <Button
                  type="button"
                  variant={selected ? "primary" : "outline"}
                  size="icon"
                  className="size-7 shrink-0"
                  aria-label={selected ? `移除 ${exercise.name}` : `加入 ${exercise.name}`}
                  onClick={() => onToggleExercise(exercise.name)}
                >
                  {selected ? <Check /> : <Plus />}
                </Button>
              </div>
            </div>
          );
        })}
        {exercises.length === 0 ? (
          <div className="rounded-lg border border-dashed border-hairline px-3 py-6 text-center text-xs text-ink-muted">
            这个肌群暂时没有对应水平的动作
          </div>
        ) : null}
      </div>

      <div className="space-y-2 border-t border-hairline px-3 py-3">
        {preferred.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {preferred.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => onToggleExercise(name)}
                className="rounded-full border border-brand/40 bg-brand-soft px-2 py-0.5 text-[11px] text-brand"
              >
                已选 {name} ×
              </button>
            ))}
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-1.5">
          {SPLITS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onSplitChange(item.value)}
              className={
                split === item.value
                  ? "rounded-lg border border-brand bg-brand-soft px-2 py-1.5 text-left"
                  : "rounded-lg border border-hairline bg-page px-2 py-1.5 text-left hover:border-brand/50"
              }
            >
              <div className="text-xs font-medium text-ink">{item.title}</div>
              <div className="mt-0.5 text-[10px] text-ink-muted">
                {item.hint}
              </div>
            </button>
          ))}
        </div>

        {error ? (
          <div className="rounded-lg border border-delta-down/40 bg-delta-down/5 px-2 py-1.5 text-xs text-ink">
            {error}
          </div>
        ) : null}

        <Button
          type="button"
          className="w-full"
          disabled={generating}
          onClick={onGenerate}
        >
          <Sparkles />
          {generating ? "生成中…" : "一键生成训练计划"}
        </Button>
        <p className="text-center text-[10px] text-ink-muted">
          每天最多 6 个动作；已选动作优先，不足再补推荐动作
        </p>
      </div>
    </div>
  );
}
