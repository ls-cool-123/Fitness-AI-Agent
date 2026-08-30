import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useVizPalette } from "@/lib/palette";
import { compact, shortDate } from "@/lib/utils";

export interface SeriesPoint {
  date: string;
  max_weight_kg: number;
  volume_kg: number;
}

/**
 * 单序列趋势折线。
 *
 * **重量和训练量各画一张，绝不合成双 Y 轴。** 双刻度的对齐是任意的，会凭空造出
 * 数据里没有的相关性；这里 kg（~100）和训练量（~10000）还差两个数量级。两张图
 * 共享同一个 X 轴域就够了。
 *
 * 同一个实现被调用两次（dataKey 不同），因此参数化；这不是为「将来可能的扩展」
 * 做的抽象。
 *
 * 其余规范细节：2px 线宽；只在**端点**放 marker（8px + 2px 表面色描环）并只标
 * 端点的值，不是每个点都标数字；网格线 1px 实线且只有水平方向；单序列不放图例框
 * （标题已经说明画的是什么）。
 */
export function TrendChart({
  data,
  dataKey,
  unit,
}: {
  data: SeriesPoint[];
  dataKey: "max_weight_kg" | "volume_kg";
  unit: string;
}) {
  const p = useVizPalette();

  if (!data.length) {
    return (
      <div className="grid h-56 place-items-center text-sm text-ink-muted">
        这段时间没有训练记录
      </div>
    );
  }

  const last = data[data.length - 1];

  return (
    // 容器高度含 X 轴标签带，避免卡片里出现嵌套滚动条
    <ResponsiveContainer width="100%" height={224}>
      <LineChart data={data} margin={{ top: 20, right: 40, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={p.grid} strokeWidth={1} vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={shortDate}
          tick={{ fill: p["text-muted"], fontSize: 11 }}
          axisLine={{ stroke: p.axis }}
          tickLine={false}
          minTickGap={24}
        />
        <YAxis
          tickFormatter={compact}
          tick={{ fill: p["text-muted"], fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={44}
        />
        <Tooltip
          // 十字准线吸附到最近日期
          cursor={{ stroke: p.axis, strokeWidth: 1 }}
          content={(props) => {
            // Recharts 的 content 回调类型很宽，就地收窄成实际用到的字段
            const { active, payload, label } = props as unknown as {
              active?: boolean;
              payload?: { value?: number }[];
              label?: string;
            };
            if (!active || !payload?.length) return null;
            return (
              <div className="rounded-lg border border-hairline bg-surface px-2.5 py-1.5 shadow-md">
                {/* 数值为主、日期为次 */}
                <div className="text-sm font-semibold text-ink">
                  {compact(payload[0].value ?? 0)}
                  <span className="ml-0.5 text-xs font-normal text-ink-2">
                    {unit}
                  </span>
                </div>
                <div className="text-xs text-ink-muted tabular">{label}</div>
              </div>
            );
          }}
        />
        <Line
          type="monotone"
          dataKey={dataKey}
          stroke={p["series-1"]}
          strokeWidth={2}
          dot={false}
          activeDot={{
            r: 4,
            fill: p["series-1"],
            stroke: p["surface-1"],
            strokeWidth: 2,
          }}
          isAnimationActive={false}
        />
        <ReferenceDot
          x={last.date}
          y={last[dataKey]}
          r={4}
          fill={p["series-1"]}
          stroke={p["surface-1"]}
          strokeWidth={2}
          label={{
            value: `${compact(last[dataKey])}${unit}`,
            position: "top",
            fill: p["text-primary"],
            fontSize: 12,
            fontWeight: 600,
          }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
