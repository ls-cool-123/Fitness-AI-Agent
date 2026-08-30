import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const RANGES = [7, 30, 90] as const;
/** 不叫 Range —— 那是 DOM 的全局类型名，别去遮它。 */
export type DayRange = (typeof RANGES)[number];

/**
 * 筛选器只有一行，放在所有内容上方。
 *
 * 关键是它**统辖下方全部图表和 KPI** —— 每张图各带一个筛选器会让读者面对互相
 * 矛盾的数字（这张图看的是 7 天、那张是 90 天），而这里所有内容始终对同一个切片
 * 重算，数字永远自洽。
 */
export function FilterRow({
  range,
  onRangeChange,
  exercise,
  exercises,
  onExerciseChange,
  onRefresh,
  loading,
}: {
  range: DayRange;
  onRangeChange: (value: DayRange) => void;
  exercise: string;
  exercises: string[];
  onExerciseChange: (value: string) => void;
  onRefresh: () => void;
  loading: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex rounded-xl border border-hairline bg-card p-1">
        {RANGES.map((days) => (
          <button
            key={days}
            type="button"
            onClick={() => onRangeChange(days)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
              range === days
                ? "bg-gradient-to-r from-brand to-brand-strong text-brand-ink shadow-sm"
                : "text-ink-2 hover:text-ink",
            )}
          >
            {days} 天
          </button>
        ))}
      </div>

      <Select
        value={exercise}
        onChange={(e) => onExerciseChange(e.target.value)}
        aria-label="选择动作"
        className="w-40"
      >
        {exercises.length === 0 ? <option value="">暂无动作</option> : null}
        {exercises.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </Select>

      <Button
        variant="outline"
        size="sm"
        onClick={onRefresh}
        disabled={loading}
        aria-label="刷新"
      >
        <RefreshCw className={loading ? "animate-spin" : undefined} />
        刷新
      </Button>
    </div>
  );
}
