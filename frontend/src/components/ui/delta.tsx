import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 变化量显示。
 *
 * 颜色只是**辅助**：一定同时带方向箭头和文字说明。dataviz 规范里 status 色
 * （good / critical）永远不能单独承载含义——色盲读者、灰度打印、forced-colors
 * 三种情况下颜色都会消失。
 *
 * @param pct - 变化百分比，正数表示上升。
 * @param label - 对比基准的说明，如「较前半段」。
 * @param upIsGood - 上升是否为好事。重量和训练量都是 true。
 */
export function Delta({
  pct,
  label,
  upIsGood = true,
  className,
}: {
  pct: number;
  label: string;
  upIsGood?: boolean;
  className?: string;
}) {
  const rising = pct > 0;
  const flat = pct === 0;
  const good = rising === upIsGood;

  const Icon = flat ? Minus : rising ? ArrowUpRight : ArrowDownRight;
  const tone = flat
    ? "text-ink-2"
    : good
      ? "text-delta-up"
      : "text-delta-down";

  return (
    <span
      className={cn("inline-flex items-baseline gap-1 text-xs font-medium", tone, className)}
    >
      <Icon className="size-3.5 shrink-0 self-center" aria-hidden="true" />
      <span className="tabular">
        {rising ? "+" : ""}
        {pct}%
      </span>
      <span className="font-normal text-ink-muted">{label}</span>
    </span>
  );
}
