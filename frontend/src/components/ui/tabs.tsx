import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export function TabsList({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        "inline-flex items-center gap-1 rounded-xl border border-hairline bg-card p-1",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-ink-2 transition-colors outline-none",
        "hover:text-ink focus-visible:ring-2 focus-visible:ring-brand",
        // 激活态用暖色渐变，和主按钮同一套语言
        "data-[state=active]:bg-gradient-to-r data-[state=active]:from-brand data-[state=active]:to-brand-strong data-[state=active]:text-brand-ink data-[state=active]:shadow-sm",
        "[&_svg]:size-4 [&_svg]:shrink-0",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      // forceMount 的内容（聊天）在非激活时 Radix 不会自动加 hidden，
      // 必须用 data-state 手动隐藏，否则切到其他 tab 后聊天面板仍占满高度。
      className={cn("outline-none data-[state=inactive]:hidden", className)}
      {...props}
    />
  );
}
