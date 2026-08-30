import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useVizPalette } from "@/lib/palette";
import { compact } from "@/lib/utils";

export interface CategoryDatum {
  category: string;
  total_volume_kg: number;
  total_sessions: number;
}

/**
 * 部位训练量分布 —— 横向柱，**7 根柱子同一个颜色**。
 *
 * 这里有个反直觉的点：不要用「越大越深」的蓝色渐变。身体部位是**名义类别**（没有
 * 自然顺序），对名义类别用值渐变是明确的反模式——它把柱长重复编码成色深，白白烧掉
 * 唯一的自由通道，而且渐变会跨越亮度带、跌破色度下限。柱长本身已经把大小说清楚了。
 *
 * 横向而非纵向：中文部位名（"手臂"、"核心"、"有氧"）竖排会挤在一起。
 */
export function CategoryVolumeChart({ data }: { data: CategoryDatum[] }) {
  const p = useVizPalette();

  if (!data.length) {
    return (
      <div className="grid h-56 place-items-center text-sm text-ink-muted">
        这段时间没有训练记录
      </div>
    );
  }

  // 值标签的文案预先算好挂在数据上：LabelList 的 formatter 类型很难对齐，
  // 直接给它一个现成的字符串字段更省事。
  const rows = data.map((row) => ({ ...row, label: compact(row.total_volume_kg) }));

  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 34 + 32)}>
      <BarChart
        data={rows}
        layout="vertical"
        barSize={20}
        barCategoryGap="30%"
        margin={{ top: 4, right: 56, bottom: 4, left: 0 }}
      >
        {/* 横向柱的网格线走竖向（沿数值轴），1px 实线 */}
        <CartesianGrid stroke={p.grid} strokeWidth={1} horizontal={false} />
        <XAxis
          type="number"
          tickFormatter={compact}
          tick={{ fill: p["text-muted"], fontSize: 11 }}
          axisLine={{ stroke: p.axis }}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="category"
          tick={{ fill: p["text-secondary"], fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={40}
        />
        <Tooltip
          // 柱图不用十字准线，每根柱子自己 hover
          cursor={false}
          content={(props) => {
            // Recharts 的 content 回调类型很宽，就地收窄成实际用到的字段
            const { active, payload } = props as unknown as {
              active?: boolean;
              payload?: { payload?: CategoryDatum }[];
            };
            const datum = payload?.[0]?.payload;
            if (!active || !datum) return null;
            return (
              <div className="rounded-lg border border-hairline bg-surface px-2.5 py-1.5 shadow-md">
                <div className="text-sm font-semibold text-ink">
                  {compact(datum.total_volume_kg)}
                  <span className="ml-0.5 text-xs font-normal text-ink-2">kg</span>
                </div>
                <div className="text-xs text-ink-muted">
                  {datum.category} · {datum.total_sessions} 次训练
                </div>
              </div>
            );
          }}
        />
        <Bar
          dataKey="total_volume_kg"
          fill={p["series-1"]}
          // 值端 4px 圆角、基线端方角
          radius={[0, 4, 4, 0]}
          isAnimationActive={false}
        >
          {/* 值标在柱外侧，永远不会被容器裁切 */}
          <LabelList
            dataKey="label"
            position="right"
            fill={p["text-secondary"]}
            fontSize={11}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
