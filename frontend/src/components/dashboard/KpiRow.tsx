import { CalendarDays, Dumbbell, Flame, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { Delta } from "@/components/ui/delta";
import { compact } from "@/lib/utils";
import type { ProgressByExercise } from "@/types/tools";

/**
 * 头条数字用 stat tile，不是图表。
 *
 * 「四个关键数字」的正确形式就是一行数值卡片——画成分组柱状图反而更难读（要在四个
 * 单位不同的量之间比柱长，毫无意义）。
 *
 * 大数字**不加** tabular-nums：等宽数字在大字号下字距会显得松散，等宽只对表格和
 * 轴刻度有用。
 */
function Tile({
  icon,
  label,
  value,
  unit,
  footer,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  unit?: string;
  footer?: ReactNode;
}) {
  return (
    <Card className="px-4 py-3">
      <div className="flex items-center gap-1.5 text-xs text-ink-2">
        <span className="text-brand [&_svg]:size-3.5">{icon}</span>
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold text-ink">
        {value}
        {unit ? (
          <span className="ml-0.5 text-sm font-normal text-ink-muted">{unit}</span>
        ) : null}
      </div>
      <div className="mt-1 h-4">{footer}</div>
    </Card>
  );
}

export function KpiRow({ analysis }: { analysis: ProgressByExercise | null }) {
  const tiles = analysis
    ? [
        {
          icon: <CalendarDays />,
          label: "训练次数",
          value: String(analysis.total_sessions),
          unit: "次",
          footer: (
            <span className="text-xs text-ink-muted">
              最近 {analysis.period_days} 天
            </span>
          ),
        },
        {
          icon: <TrendingUp />,
          label: "每周频率",
          value: String(analysis.sessions_per_week),
          unit: "次/周",
          footer: null,
        },
        {
          icon: <Dumbbell />,
          label: "最近最大重量",
          value: compact(analysis.latest_max_weight_kg),
          unit: "kg",
          footer: (
            <Delta pct={analysis.max_weight_change_pct} label="较前半段" />
          ),
        },
        {
          icon: <Flame />,
          label: "训练量",
          value: compact(analysis.avg_volume_second_half),
          unit: "kg",
          footer: <Delta pct={analysis.volume_change_pct} label="较前半段" />,
        },
      ]
    : [];

  if (!tiles.length) {
    return (
      <Card className="px-4 py-6 text-center text-sm text-ink-muted">
        这个动作在所选时间范围内还没有记录
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((tile) => (
        <Tile key={tile.label} {...tile} />
      ))}
    </div>
  );
}
