import { CalendarDays, History, Loader2, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { AnatomyViewer } from "@/components/plan/AnatomyViewer";
import { MusclePanel } from "@/components/plan/MusclePanel";
import { TrainingPlanCard } from "@/components/plan/TrainingPlanCard";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import {
  deletePlan,
  fetchPlan,
  fetchPlanMuscles,
  fetchPlans,
  generatePlan,
  swapPlanExercises,
} from "@/lib/api";
import type {
  Experience,
  PlanMuscleCatalog,
  PlanMuscleGroup,
  PlanSummary,
  PlanSwap,
  Split,
  TrainingPlan,
} from "@/types/plan";

const SPLIT_LABEL: Record<string, string> = {
  three_day: "三分化",
  five_day: "五分化",
};

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("zh-CN");
}

/** 人体图 + 动作面板 + 一键生成 + 我的计划。 */
export function PlanStudio({ userId }: { userId: string }) {
  const [catalog, setCatalog] = useState<PlanMuscleCatalog | null>(null);
  const [selectedId, setSelectedId] = useState<PlanMuscleGroup["id"] | null>(null);
  const [level, setLevel] = useState<Experience>("beginner");
  const [split, setSplit] = useState<Split>("three_day");
  const [preferred, setPreferred] = useState<string[]>([]);
  const [plan, setPlan] = useState<TrainingPlan | null>(null);
  const [history, setHistory] = useState<PlanSummary[]>([]);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedGroup =
    catalog?.groups.find((group) => group.id === selectedId) ?? null;

  useEffect(() => {
    const controller = new AbortController();
    setLoadingCatalog(true);
    fetchPlanMuscles(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setCatalog(data);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingCatalog(false);
      });
    return () => controller.abort();
  }, []);

  const refreshHistory = useCallback(() => {
    fetchPlans(userId, 20)
      .then(setHistory)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
      });
  }, [userId]);

  useEffect(() => {
    setPlan(null);
    setError(null);
    const controller = new AbortController();
    fetchPlans(userId, 20, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setHistory(items);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => controller.abort();
  }, [userId]);

  function toggleExercise(name: string) {
    setPreferred((prev) =>
      prev.includes(name) ? prev.filter((item) => item !== name) : [...prev, name],
    );
  }

  async function generate() {
    if (!selectedGroup || generating) return;
    setGenerating(true);
    setError(null);
    try {
      const created = await generatePlan({
        user_id: userId,
        experience: level,
        split,
        focus_muscles: [selectedGroup.name],
        preferred_exercises: preferred,
        goal: "增肌",
      });
      setPlan(created);
      setPreferred([]);
      refreshHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  async function saveSwaps(swaps: PlanSwap[]) {
    if (!plan) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await swapPlanExercises({
        userId,
        planId: plan.plan_id,
        swaps,
      });
      setPlan(updated);
      refreshHistory();
    } finally {
      setSaving(false);
    }
  }

  async function removePlan(planId: string) {
    if (deleting) return;
    setDeleting(true);
    setError(null);
    try {
      await deletePlan(userId, planId);
      if (plan?.plan_id === planId) setPlan(null);
      refreshHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  }

  async function openPlan(planId: string) {
    if (opening) return;
    setOpening(true);
    setError(null);
    try {
      const loaded = await fetchPlan(userId, planId);
      setPlan(loaded);
      const first = catalog?.groups.find((group) =>
        loaded.focus_muscles.includes(group.name),
      );
      if (first) setSelectedId(first.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOpening(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-ink">人体图 · 打造训练计划</h2>
          <p className="mt-0.5 text-xs text-ink-2">
            点肌肉 → 看新手/老手动作 → 选三分化或五分化 → 一键生成
          </p>
        </div>
        <span className="rounded-full border border-hairline bg-card px-2.5 py-1 text-[11px] text-ink-muted">
          模型：Z-Anatomy / hpfrei · CC BY-SA 4.0
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {loadingCatalog ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-ink-muted">
            <Loader2 className="size-3.5 animate-spin" />
            加载动作库…
          </span>
        ) : catalog ? (
          catalog.groups.map((group) => (
            <button
              key={group.id}
              type="button"
              aria-pressed={selectedId === group.id}
              onClick={() => setSelectedId(group.id)}
              className={
                selectedId === group.id
                  ? "rounded-full border border-brand bg-brand-soft px-3 py-1 text-xs font-medium text-brand"
                  : "rounded-full border border-hairline bg-card px-3 py-1 text-xs text-ink-2 transition-colors hover:border-brand hover:text-brand"
              }
            >
              {group.name}
            </button>
          ))
        ) : (
          <span className="text-xs text-ink-muted">
            动作库加载失败，3D 图仍可查看；请检查后端 /plan 接口。
          </span>
        )}
      </div>

      {error ? (
        <div className="rounded-lg border border-delta-down/40 bg-delta-down/5 px-3 py-2 text-sm text-ink">
          {error}
        </div>
      ) : null}

      <div className="grid items-stretch gap-4 lg:grid-cols-[1.35fr_1fr]">
        <AnatomyViewer
          selectedGroup={selectedId}
          onSelectGroup={(group) => setSelectedId(group)}
        />
        <MusclePanel
          group={selectedGroup}
          level={level}
          onLevelChange={setLevel}
          split={split}
          onSplitChange={setSplit}
          preferred={preferred}
          onToggleExercise={toggleExercise}
          onGenerate={() => void generate()}
          generating={generating}
          error={null}
        />
      </div>

      {plan ? (
        <TrainingPlanCard
          plan={plan}
          onSave={saveSwaps}
          saving={saving}
          onDelete={() => removePlan(plan.plan_id)}
          deleting={deleting}
        />
      ) : (
        <div className="rounded-xl border border-dashed border-hairline px-4 py-6 text-center">
          <Sparkles className="mx-auto size-5 text-brand" aria-hidden="true" />
          <p className="mt-2 text-sm text-ink-2">
            选好肌群和分化后，点「一键生成训练计划」；生成结果会出现在这里并自动保存。
          </p>
        </div>
      )}

      <Card>
        <CardHeader
          icon={<History />}
          title="我的计划"
          subtitle="按生成时间倒序；点击可查看并继续换动作"
          action={
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={opening}
              onClick={refreshHistory}
            >
              <CalendarDays />
              刷新
            </Button>
          }
        />
        <CardBody>
          {history.length === 0 ? (
            <p className="text-xs text-ink-muted">
              还没有保存过计划。人体图生成或 AI 对话确认后都会出现在这里。
            </p>
          ) : (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {history.map((item) => (
                <button
                  key={item.plan_id}
                  type="button"
                  onClick={() => void openPlan(item.plan_id)}
                  className="flex items-center justify-between gap-2 rounded-lg border border-hairline bg-page px-3 py-2 text-left transition-colors hover:border-brand/60"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-ink">
                      {item.name}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-ink-muted">
                      {SPLIT_LABEL[item.split] ?? item.split} · {item.day_count} 天 ·{" "}
                      {dateLabel(item.created_at)}
                    </span>
                  </span>
                  <span className="shrink-0 rounded-full bg-brand-soft px-2 py-0.5 text-[10px] text-brand">
                    {item.source === "chat" ? "AI" : "人体图"}
                  </span>
                </button>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
