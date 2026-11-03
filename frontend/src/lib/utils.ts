import { clsx } from "clsx";
import type { ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn 约定的类名合并：clsx 处理条件，tailwind-merge 消解冲突的工具类。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 大数字紧凑显示：1,284 / 12.9K / 1.2M。用于 KPI 卡片的值。 */
export function compact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `${(value / 1000).toFixed(1)}K`;
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 1 });
}

/** 轴刻度用的千分位整数。 */
export function thousands(value: number): string {
  return Math.round(value).toLocaleString("zh-CN");
}

/** 把 2026-08-29 缩成 08-29，给 X 轴刻度用（完整日期留给 tooltip 和表格）。 */
export function shortDate(iso: string): string {
  return iso.length >= 10 ? iso.slice(5) : iso;
}
