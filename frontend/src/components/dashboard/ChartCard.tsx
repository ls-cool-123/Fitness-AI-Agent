import { useState } from "react";
import type { ReactNode } from "react";

import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * 图表卡片外壳 —— 统一处理「图表 / 表格」双视图。
 *
 * dataviz 规范要求每张图都有表格孪生体：tooltip 只能增强读数，不能是读数的唯一
 * 途径（键盘用户、截图、屏幕阅读器都拿不到 hover）。切换器放在卡片头部而不是页面
 * 级，因为三张图各自的表格结构不同。
 */
export function ChartCard({
  title,
  subtitle,
  icon,
  chart,
  table,
  dimmed,
}: {
  title: string;
  subtitle?: string;
  icon: ReactNode;
  chart: ReactNode;
  table: ReactNode;
  /** 重新取数期间降不透明度，保持旧渲染不跳布局 */
  dimmed?: boolean;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");

  return (
    <Card>
      <CardHeader
        icon={icon}
        title={title}
        subtitle={subtitle}
        action={
          <div className="flex rounded-lg border border-hairline p-0.5 text-xs">
            {(["chart", "table"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setView(mode)}
                className={cn(
                  "rounded-md px-2 py-1 font-medium transition-colors",
                  view === mode
                    ? "bg-brand-soft text-brand"
                    : "text-ink-muted hover:text-ink-2",
                )}
              >
                {mode === "chart" ? "图表" : "表格"}
              </button>
            ))}
          </div>
        }
      />
      <CardBody
        className={cn("transition-opacity", dimmed && "opacity-60")}
      >
        {view === "chart" ? chart : table}
      </CardBody>
    </Card>
  );
}
