import type { ReactNode } from "react";

export interface Column {
  key: string;
  label: string;
  /** 数值列右对齐，文本列左对齐 */
  numeric?: boolean;
}

/**
 * 图表的表格孪生体。
 *
 * 数值列用 tabular-nums 让小数点对齐（表格和轴刻度是等宽数字唯一该用的地方，
 * KPI 大数字反而要比例字形）。
 */
export function TableView({
  columns,
  rows,
  empty = "这段时间没有数据",
}: {
  columns: Column[];
  rows: Record<string, ReactNode>[];
  empty?: string;
}) {
  if (!rows.length) {
    return <div className="py-8 text-center text-sm text-ink-muted">{empty}</div>;
  }

  return (
    <div className="max-h-64 overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card">
          <tr className="border-b border-hairline">
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={
                  col.numeric
                    ? "py-1.5 pl-3 text-right text-xs font-medium text-ink-2"
                    : "py-1.5 text-left text-xs font-medium text-ink-2"
                }
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-hairline last:border-0">
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={
                    col.numeric
                      ? "py-1.5 pl-3 text-right text-ink-2 tabular"
                      : "py-1.5 text-left text-ink"
                  }
                >
                  {row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
