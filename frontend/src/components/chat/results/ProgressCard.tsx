import { CalendarDays, Dumbbell, Flame, Trophy } from "lucide-react";
import type { ReactNode } from "react";

import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Delta } from "@/components/ui/delta";
import { compact } from "@/lib/utils";
import type { ProgressByExercise } from "@/types/tools";

const TREND_TEXT: Record<ProgressByExercise["trend_direction"], string> = {
  up: "在进步",
  down: "有回落",
  stable: "保持稳定",
};

function Metric({
  icon,
  label,
  value,
  unit,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="rounded-lg border border-hairline bg-page px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-xs text-ink-2">
        <span className="text-brand [&_svg]:size-3.5">{icon}</span>
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-ink">
        {value}
        {unit ? (
          <span className="ml-0.5 text-xs font-normal text-ink-muted">{unit}</span>
        ) : null}
      </div>
    </div>
  );
}

/** analyze_progress_tool 模式 1（单动作趋势）的结果卡片。 */
export function ProgressCard({ data }: { data: ProgressByExercise }) {
  return (
    <Card>
      <CardHeader
        icon={<Dumbbell />}
        title={`${data.exercise} · ${TREND_TEXT[data.trend_direction]}`}
        subtitle={`最近 ${data.period_days} 天，共 ${data.total_sessions} 次训练`}
      />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric
            icon={<Dumbbell />}
            label="最近最大重量"
            value={compact(data.latest_max_weight_kg)}
            unit="kg"
          />
          <Metric
            icon={<Trophy />}
            label="周期内最佳"
            value={compact(data.all_time_max_weight_kg)}
            unit="kg"
          />
          <Metric
            icon={<Flame />}
            label="后半段训练量"
            value={compact(data.avg_volume_second_half)}
            unit="kg"
          />
          <Metric
            icon={<CalendarDays />}
            label="每周频率"
            value={String(data.sessions_per_week)}
            unit="次"
          />
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-hairline pt-3">
          <div className="flex items-baseline gap-2">
            <span className="text-xs text-ink-2">最大重量</span>
            <Delta pct={data.max_weight_change_pct} label="较前半段" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-xs text-ink-2">训练量</span>
            <Delta pct={data.volume_change_pct} label="较前半段" />
          </div>
          <span className="text-xs text-ink-muted tabular">
            {data.avg_max_weight_first_half_kg}kg →{" "}
            {data.avg_max_weight_second_half_kg}kg
          </span>
        </div>
      </CardBody>
    </Card>
  );
}
