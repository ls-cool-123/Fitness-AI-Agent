import { CalendarDays } from "lucide-react";

import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { WorkoutItemDto, WorkoutSessionDto } from "@/types/tools";

/**
 * 把一个动作压成一行可读文本。
 *
 * `sets` / `reps` / `weight_kg` 都可能是 null（有氧类动作只记时长和距离），
 * 所以每一段都要单独判空，不能假设它们同时存在。
 */
function describe(item: WorkoutItemDto): string {
  const parts: string[] = [];
  if (item.sets != null) parts.push(`${item.sets} 组`);
  if (item.reps != null) parts.push(`${item.reps} 次`);
  if (item.weight_kg != null && item.weight_kg > 0) parts.push(`${item.weight_kg} kg`);
  return parts.join(" × ") || "—";
}

/** 每组明细形如 `12×60 / 10×60 / 8×60`，只在各组不一致时才值得展开。 */
function setDetailText(item: WorkoutItemDto): string | null {
  const details = item.set_details;
  if (!details || details.length <= 1) return null;
  const uniform = details.every(
    (d) => d.reps === details[0].reps && d.weight_kg === details[0].weight_kg,
  );
  if (uniform) return null;
  return details.map((d) => `${d.reps}×${d.weight_kg}`).join(" / ");
}

/** query_workout_tool 的结果表格。 */
export function WorkoutTable({ sessions }: { sessions: WorkoutSessionDto[] }) {
  return (
    <Card>
      <CardHeader
        icon={<CalendarDays />}
        title="训练记录"
        subtitle={`${sessions.length} 次训练`}
      />
      <CardBody className="space-y-3">
        {sessions.map((session) => (
          <div key={session.session_id}>
            <div className="mb-1.5 flex items-baseline gap-2">
              <span className="text-sm font-semibold text-ink tabular">
                {session.date}
              </span>
              {session.notes ? (
                <span className="truncate text-xs text-ink-muted">
                  {session.notes}
                </span>
              ) : null}
            </div>
            <table className="w-full text-sm">
              <tbody>
                {session.items.map((item, i) => {
                  const detail = setDetailText(item);
                  return (
                    <tr
                      key={`${item.exercise}-${i}`}
                      className="border-t border-hairline"
                    >
                      <td className="py-1.5 pr-3 text-ink">{item.exercise}</td>
                      <td className="w-px py-1.5 text-right whitespace-nowrap text-ink-2 tabular">
                        {describe(item)}
                      </td>
                      <td className="w-px py-1.5 pl-3 text-right whitespace-nowrap text-xs text-ink-muted tabular">
                        {detail ?? ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
