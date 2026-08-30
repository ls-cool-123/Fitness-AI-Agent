import { AlertTriangle, BarChart3, Flame, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CategoryVolumeChart } from "@/components/dashboard/CategoryVolumeChart";
import type { CategoryDatum } from "@/components/dashboard/CategoryVolumeChart";
import { ChartCard } from "@/components/dashboard/ChartCard";
import { FilterRow } from "@/components/dashboard/FilterRow";
import type { DayRange } from "@/components/dashboard/FilterRow";
import { KpiRow } from "@/components/dashboard/KpiRow";
import { TableView } from "@/components/dashboard/TableView";
import { TrendChart } from "@/components/dashboard/TrendChart";
import type { SeriesPoint } from "@/components/dashboard/TrendChart";
import { fetchCategorySummary, fetchHistory, fetchProgress } from "@/lib/api";
import { compact, thousands } from "@/lib/utils";
import { isProgressByExercise } from "@/types/tools";
import type { ProgressByExercise } from "@/types/tools";

/** 动作下拉框的候选项。用 90 天而不是当前筛选范围，避免切到 7 天后选项凭空消失。 */
const EXERCISE_LOOKBACK_DAYS = 90;
/** /workout/history 的 limit 上限是 50（后端 Query(le=50)），别传更大的值否则 422。 */
const EXERCISE_LOOKBACK_LIMIT = 50;

export function Dashboard({ userId }: { userId: string }) {
  const [range, setRange] = useState<DayRange>(30);
  const [exercise, setExercise] = useState("");
  const [exercises, setExercises] = useState<string[]>([]);

  const [analysis, setAnalysis] = useState<ProgressByExercise | null>(null);
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [categories, setCategories] = useState<CategoryDatum[]>([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  // 动作候选项：从训练历史里抽出去重后的动作名
  useEffect(() => {
    const controller = new AbortController();
    fetchHistory({
      userId,
      daysBack: EXERCISE_LOOKBACK_DAYS,
      limit: EXERCISE_LOOKBACK_LIMIT,
      signal: controller.signal,
    })
      .then((sessions) => {
        const names = [
          ...new Set(sessions.flatMap((s) => s.items.map((i) => i.exercise))),
        ];
        setExercises(names);
        setExercise((prev) => (prev && names.includes(prev) ? prev : (names[0] ?? "")));
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => controller.abort();
  }, [userId, reloadKey]);

  // 趋势与 KPI。刻意不在请求开始时清空旧数据 —— 保持画面，只降不透明度。
  useEffect(() => {
    if (!exercise) {
      setAnalysis(null);
      setSeries([]);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchProgress({
      userId,
      exerciseName: exercise,
      daysBack: range,
      signal: controller.signal,
    })
      .then((res) => {
        setAnalysis(isProgressByExercise(res.analysis) ? res.analysis : null);
        setSeries(res.series);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [userId, exercise, range, reloadKey]);

  // 部位分布：不受动作筛选影响，只跟时间范围走
  useEffect(() => {
    const controller = new AbortController();
    fetchCategorySummary({ userId, daysBack: range, signal: controller.signal })
      .then((res) => setCategories(res.categories))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => controller.abort();
  }, [userId, range, reloadKey]);

  return (
    <div className="space-y-4">
      <FilterRow
        range={range}
        onRangeChange={setRange}
        exercise={exercise}
        exercises={exercises}
        onExerciseChange={setExercise}
        onRefresh={refresh}
        loading={loading}
      />

      {error ? (
        <div className="flex items-start gap-2 rounded-lg border border-delta-down/40 bg-delta-down/5 px-3 py-2.5 text-sm text-ink">
          <AlertTriangle
            className="mt-0.5 size-4 shrink-0 text-delta-down"
            aria-hidden="true"
          />
          <div>
            <div className="font-medium">数据加载失败</div>
            <div className="mt-0.5 text-xs text-ink-2">{error}</div>
          </div>
        </div>
      ) : null}

      <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
        <KpiRow analysis={analysis} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard
          icon={<TrendingUp />}
          title={exercise ? `${exercise} · 最大重量趋势` : "最大重量趋势"}
          subtitle={`最近 ${range} 天，单位 kg`}
          dimmed={loading}
          chart={<TrendChart data={series} dataKey="max_weight_kg" unit="kg" />}
          table={
            <TableView
              columns={[
                { key: "date", label: "日期" },
                { key: "weight", label: "最大重量 (kg)", numeric: true },
              ]}
              rows={series.map((point) => ({
                date: point.date,
                weight: compact(point.max_weight_kg),
              }))}
            />
          }
        />

        <ChartCard
          icon={<Flame />}
          title={exercise ? `${exercise} · 训练量趋势` : "训练量趋势"}
          subtitle={`最近 ${range} 天，训练量 = 重量 × 组数 × 次数`}
          dimmed={loading}
          chart={<TrendChart data={series} dataKey="volume_kg" unit="kg" />}
          table={
            <TableView
              columns={[
                { key: "date", label: "日期" },
                { key: "volume", label: "训练量 (kg)", numeric: true },
              ]}
              rows={series.map((point) => ({
                date: point.date,
                volume: thousands(point.volume_kg),
              }))}
            />
          }
        />
      </div>

      <ChartCard
        icon={<BarChart3 />}
        title="各部位训练量分布"
        subtitle={`最近 ${range} 天，全部动作`}
        chart={<CategoryVolumeChart data={categories} />}
        table={
          <TableView
            columns={[
              { key: "category", label: "部位" },
              { key: "volume", label: "训练量 (kg)", numeric: true },
              { key: "sessions", label: "训练次数", numeric: true },
            ]}
            rows={categories.map((row) => ({
              category: row.category,
              volume: thousands(row.total_volume_kg),
              sessions: row.total_sessions,
            }))}
          />
        }
      />
    </div>
  );
}
