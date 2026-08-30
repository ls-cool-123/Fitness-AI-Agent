import { cva } from "class-variance-authority";
import type { VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-semibold whitespace-nowrap transition-all outline-none disabled:pointer-events-none disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-page [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // 主操作：暖色渐变 + 悬停微微上浮，界面活力主要来自这里
        primary:
          "bg-gradient-to-r from-brand to-brand-strong text-brand-ink shadow-sm hover:shadow-md hover:-translate-y-px active:translate-y-0",
        outline:
          "border border-hairline bg-card text-ink hover:border-brand hover:text-brand",
        ghost: "text-ink-2 hover:bg-brand-soft hover:text-brand",
        danger: "text-ink-muted hover:bg-brand-soft hover:text-delta-down",
      },
      size: {
        sm: "h-8 px-3",
        md: "h-10 px-4",
        icon: "size-8 p-0",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return (
    <button
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
