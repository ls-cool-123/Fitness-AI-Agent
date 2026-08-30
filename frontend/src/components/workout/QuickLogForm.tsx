import { Dumbbell, Plus, Save, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { addWorkout } from "@/lib/api";
import type { ExercisePayload } from "@/lib/api";

const DEFAULT_REPS = 10;
const MAX_SETS = 20;

/** 把数组按新长度裁剪或补齐，已填的值原样保留。 */
function resize(arr: number[], size: number, fill: number): number[] {
  if (size <= arr.length) return arr.slice(0, size);
  return [...arr, ...Array<number>(size - arr.length).fill(fill)];
}

function clamp(raw: string, min: number, max: number): number {
  const n = Number(raw);
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}

/**
 * 汇总文案 —— 按「每组次数是否一致」×「每组重量是否一致」分四种情况，
 * 与旧版表单的四个分支逐字对应。重量都相同时全一致就用一行。
 */
function summarize(reps: number[], weights: number[]): string[] {
  const totalReps = reps.reduce((a, b) => a + b, 0);
  const sameReps = new Set(reps).size === 1;
  const sameWeights = new Set(weights).size === 1;
  const w0 = weights[0] > 0 ? `${weights[0]}kg` : "自重";
  const repsList = reps.join(", ");
  const weightsList = weights.map((w) => `${w}kg`).join(", ");

  if (sameReps && sameWeights) return [`共 ${totalReps} 次，${w0}`];
  if (sameReps) return [`共 ${totalReps} 次，重量 ${weightsList}`];
  if (sameWeights) return [`次数 ${repsList}，共 ${totalReps} 次，${w0}`];
  return [`次数 ${repsList}，共 ${totalReps} 次`, `重量 ${weightsList}`];
}

/** 仅当每组次数或重量不一致时才写备注 —— 一致的话汇总值已经表达完整了。 */
function buildNotes(reps: number[], weights: number[]): string | null {
  const parts: string[] = [];
  if (new Set(reps).size > 1) parts.push(`每组次数:${reps.join(",")}`);
  if (new Set(weights).size > 1) parts.push(`每组重量:${weights.join(",")}`);
  return parts.length ? parts.join("; ") : null;
}

export function QuickLogForm({ userId }: { userId: string }) {
  const [name, setName] = useState("");
  const [reps, setReps] = useState<number[]>(Array(3).fill(DEFAULT_REPS));
  const [weights, setWeights] = useState<number[]>(Array(3).fill(0));
  const [pending, setPending] = useState<ExercisePayload[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<
    { ok: boolean; text: string } | null
  >(null);

  const sets = reps.length;
  const summary = summarize(reps, weights);

  function setSets(next: number) {
    setReps((prev) => resize(prev, next, DEFAULT_REPS));
    setWeights((prev) => resize(prev, next, 0));
  }

  function addToList() {
    const trimmed = name.trim();
    if (!trimmed) {
      setFeedback({ ok: false, text: "请输入动作名称" });
      return;
    }
    // 平均重量只统计非零项：0 表示自重训练，算进均值会把它压低
    const nonzero = weights.filter((w) => w > 0);
    const avgWeight = nonzero.length
      ? Math.round((nonzero.reduce((a, b) => a + b, 0) / nonzero.length) * 10) / 10
      : 0;

    setPending((prev) => [
      ...prev,
      {
        name: trimmed,
        sets,
        reps: reps.reduce((a, b) => a + b, 0),
        weight_kg: avgWeight,
        set_details: reps.map((r, i) => ({ reps: r, weight_kg: weights[i] })),
        notes: buildNotes(reps, weights),
      },
    ]);
    // 只清动作名：组数/次数/重量通常和下一个动作相近，留着省一次重填
    setName("");
    setFeedback(null);
  }

  async function submit() {
    if (!pending.length || submitting) return;
    setSubmitting(true);
    setFeedback(null);
    try {
      const res = await addWorkout(userId, pending);
      setPending([]);
      setFeedback({ ok: true, text: res.message || "已记录" });
    } catch (err) {
      setFeedback({
        ok: false,
        text: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader
        icon={<Dumbbell />}
        title="记录训练"
        subtitle="填好一个动作加入列表，攒齐了一次提交"
      />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-[1fr_5rem] gap-2">
          <Field label="动作名称">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="深蹲"
            />
          </Field>
          <Field label="组数">
            <Input
              type="number"
              min={1}
              max={MAX_SETS}
              value={sets}
              onChange={(e) => setSets(clamp(e.target.value, 1, MAX_SETS))}
            />
          </Field>
        </div>

        <div>
          <div className="mb-1.5 text-xs font-medium text-ink-2">每组次数与重量</div>
          <div className="max-h-52 space-y-1.5 overflow-y-auto pr-1">
            {reps.map((r, i) => (
              <div key={i} className="flex items-center gap-1.5">
                <span className="w-10 shrink-0 text-xs text-ink-muted tabular">
                  第{i + 1}组
                </span>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={r}
                  aria-label={`第${i + 1}组次数`}
                  onChange={(e) =>
                    setReps((prev) =>
                      prev.map((v, j) =>
                        j === i ? clamp(e.target.value, 0, 100) : v,
                      ),
                    )
                  }
                />
                <span className="shrink-0 text-xs text-ink-muted">次</span>
                <Input
                  type="number"
                  min={0}
                  max={999}
                  step={2.5}
                  value={weights[i]}
                  aria-label={`第${i + 1}组重量`}
                  onChange={(e) =>
                    setWeights((prev) =>
                      prev.map((v, j) =>
                        j === i ? clamp(e.target.value, 0, 999) : v,
                      ),
                    )
                  }
                />
                <span className="shrink-0 text-xs text-ink-muted">kg</span>
              </div>
            ))}
          </div>
          <div className="mt-1.5 space-y-0.5">
            {summary.map((line) => (
              <div key={line} className="text-xs text-ink-muted">
                {line}
              </div>
            ))}
          </div>
        </div>

        <Button variant="outline" size="sm" className="w-full" onClick={addToList}>
          <Plus />
          添加到列表
        </Button>

        {pending.length > 0 ? (
          <div className="space-y-1.5 border-t border-hairline pt-3">
            <div className="text-xs font-medium text-ink-2">
              已添加 {pending.length} 个动作
            </div>
            {pending.map((ex, i) => (
              <div
                key={i}
                className="flex items-center gap-2 rounded-lg border border-hairline bg-page px-2.5 py-1.5 text-sm"
              >
                <span className="min-w-0 flex-1 truncate text-ink">{ex.name}</span>
                <span className="shrink-0 text-xs text-ink-2 tabular">
                  {ex.sets}组 {ex.notes ?? `${ex.reps}次`}
                </span>
                <span className="shrink-0 text-xs text-ink-2 tabular">
                  {ex.weight_kg > 0 ? `${ex.weight_kg}kg` : "自重"}
                </span>
                <Button
                  variant="danger"
                  size="icon"
                  aria-label={`删除 ${ex.name}`}
                  onClick={() =>
                    setPending((prev) => prev.filter((_, j) => j !== i))
                  }
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
            <Button
              className="w-full"
              size="sm"
              disabled={submitting}
              onClick={() => void submit()}
            >
              <Save />
              {submitting ? "提交中…" : "记录训练"}
            </Button>
          </div>
        ) : null}

        {feedback ? (
          <div
            className={
              feedback.ok
                ? "text-xs text-delta-up"
                : "text-xs text-delta-down"
            }
          >
            {feedback.text}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
