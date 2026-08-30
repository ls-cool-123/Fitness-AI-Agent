import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

const fieldStyles =
  "h-9 w-full rounded-lg border border-hairline bg-page px-3 text-sm text-ink outline-none transition-colors placeholder:text-ink-muted focus:border-brand focus:ring-2 focus:ring-brand/30 disabled:opacity-50";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input data-slot="input" className={cn(fieldStyles, className)} {...props} />
  );
}

/**
 * 原生 select —— 没有引 Radix Select。
 * 选项少、需要键盘和移动端原生行为，原生控件在这里更合适也更省依赖。
 */
export function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      data-slot="select"
      className={cn(fieldStyles, "cursor-pointer pr-8", className)}
      {...props}
    />
  );
}

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-xs font-medium text-ink-2">{label}</span>
      {children}
      {hint ? (
        <span className="mt-1 block text-xs text-ink-muted">{hint}</span>
      ) : null}
    </label>
  );
}
