import { Activity, Flame, Layers, Repeat } from "lucide-react";
import type { ReactNode } from "react";

import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { compact, thousands } from "@/lib/utils";
import type { ProgressByCategory } from "@/types/tools";

function Stat({
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

/** analyze_progress_tool 模式 2（按部位聚合）的结果卡片。 */
export function CategoryCard({ data }: { data: ProgressByCategory }) {
  return (
    <Card>
      <CardHeader
        icon={<Layers />}
        title={`${data.category} · 训练概览`}
        subtitle={`最近 ${data.period_days} 天，共 ${data.total_sessions} 次训练（每周 ${data.sessions_per_week} 次）`}
      />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat
            icon={<Flame />}
            label="总训练量"
            value={compact(data.total_volume_kg)}
            unit="kg"
          />
          <Stat
            icon={<Layers />}
            label="总组数"
            value={thousands(data.total_sets)}
            unit="组"
          />
          <Stat
            icon={<Repeat />}
            label="总次数"
            value={thousands(data.total_reps)}
            unit="次"
          />
          <Stat
            icon={<Activity />}
            label="动作种类"
            value={String(data.total_exercises)}
            unit="个"
          />
        </div>

        {data.exercises.length > 0 ? (
          <div className="border-t border-hairline pt-3">
            <div className="mb-1.5 text-xs text-ink-2">练过的动作</div>
            <div className="flex flex-wrap gap-1.5">
              {data.exercises.map((name) => (
                <span
                  key={name}
                  className="rounded-full bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand"
                >
                  {name}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
