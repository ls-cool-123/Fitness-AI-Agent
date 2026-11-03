import {
  CircleCheck,
  CircleX,
  ClipboardCheck,
  Clock,
  Loader2,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type {
  ConfirmEdit,
  ConfirmStatus,
  ConfirmWorkoutInterruptValue,
  WorkoutPreviewItem,
} from "@/types/chat";

export type { ConfirmStatus };

/** 输入框里保留原始字符串，允许用户暂时清空，提交时再转数字。 */
interface EditableRow {
  name: string;
  sets: string;
  reps: string;
  weight_kg: string;
}

function toRow(item: WorkoutPreviewItem): EditableRow {
  // 后端 reps 是总次数，卡片编辑的是每组次数：优先用 reps_per_set，
  // 否则（例如有氧项没有组数）退回 reps，避免 5 组 5 次显示成 5 组 25 次
  const perSet = item.reps_per_set ?? item.reps;
  return {
    name: item.name,
    sets: item.sets == null ? "" : String(item.sets),
    reps: perSet == null ? "" : String(perSet),
    weight_kg: item.weight_kg == null ? "" : String(item.weight_kg),
  };
}

/** type=number 仍可能被程序填入非法值，统一按「空 = null，负数按 0」处理。 */
function parseInteger(raw: string): number | null {
  if (!raw.trim()) return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return Math.max(0, Math.trunc(value));
}

function parseNumber(raw: string): number | null {
  if (!raw.trim()) return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return Math.max(0, value);
}

/**
 * 把卡片当前数值组装成 edits 回传。
 *
 * 没改过的行原样带回，`set_details` / `notes` 这些卡片上没有编辑入口的信息因此
 * 不会因为一次确认而丢失；改过组数/次数/重量的行，原来按组拆的明细已不再成立，
 * 只能清掉让后端按新值重建。
 */
function buildEdits(
  rows: EditableRow[],
  preview: WorkoutPreviewItem[],
): ConfirmEdit[] {
  return rows.map((row, i) => {
    const original = preview[i];
    const sets = parseInteger(row.sets);
    const reps = parseInteger(row.reps);
    const weight = parseNumber(row.weight_kg);

    const originalPerSet = original.reps_per_set ?? original.reps;
    if (
      sets === original.sets &&
      reps === originalPerSet &&
      weight === original.weight_kg
    ) {
      return { ...original };
    }

    return {
      name: original.name,
      sets,
      // 总次数 = 组数 × 每组次数；同时回传 reps_per_set，后端以它为准重算
      reps: sets != null && reps != null ? sets * reps : null,
      reps_per_set: reps,
      weight_kg: weight,
      set_details: null,
      notes: original.notes,
    };
  });
}

/** 终态下的只读摘要，格式与训练记录表格保持一致。 */
function describe(row: EditableRow): string {
  const parts: string[] = [];
  if (row.sets.trim()) parts.push(`${row.sets.trim()} 组`);
  if (row.reps.trim()) parts.push(`${row.reps.trim()} 次`);
  const weight = parseNumber(row.weight_kg);
  parts.push(weight != null && weight > 0 ? `${weight} kg` : "自重");
  return parts.join(" × ");
}

const TERMINAL_TEXT: Record<"confirmed" | "cancelled" | "expired", string> = {
  confirmed: "已确认，训练记录已写入",
  cancelled: "已取消，本次没有写入任何数据",
  expired: "该操作已处理或已过期",
};

function terminalText(status: ConfirmStatus): string | null {
  if (status === "confirmed") return TERMINAL_TEXT.confirmed;
  if (status === "cancelled") return TERMINAL_TEXT.cancelled;
  if (status === "expired") return TERMINAL_TEXT.expired;
  return null;
}

export function WorkoutConfirmCard({
  request,
  status,
  error,
  onConfirm,
  onCancel,
}: {
  request: ConfirmWorkoutInterruptValue;
  status: ConfirmStatus;
  error: string | null;
  /** edits 是卡片当前数值，用户没改的行也会原样回传。 */
  onConfirm: (edits: ConfirmEdit[]) => Promise<void> | void;
  onCancel: () => Promise<void> | void;
}) {
  const [rows, setRows] = useState<EditableRow[]>(() =>
    request.preview.map(toRow),
  );
  const [submittingAction, setSubmittingAction] = useState<
    "confirm" | "cancel" | null
  >(null);

  const busy = status === "submitting" || submittingAction !== null;
  const finalText = terminalText(status);
  const terminal = finalText !== null;
  // 只有确认成功时展示用户改过的值（那才是真正落库的数据）；取消/失效时
  // 回退到 Agent 原始解析结果，避免把没写入的编辑内容当成已生效。
  const displayRows =
    terminal && status !== "confirmed" ? request.preview.map(toRow) : rows;

  function updateRow(
    index: number,
    field: "sets" | "reps" | "weight_kg",
    value: string,
  ) {
    setRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    );
  }

  async function submit(action: "confirm" | "cancel") {
    if (busy) return;
    setSubmittingAction(action);
    try {
      if (action === "confirm") {
        await onConfirm(buildEdits(rows, request.preview));
      } else {
        await onCancel();
      }
    } finally {
      setSubmittingAction(null);
    }
  }

  const header = (() => {
    if (status === "confirmed") {
      return {
        icon: <CircleCheck />,
        title: "已确认",
        subtitle: "训练记录已写入",
      };
    }
    if (status === "cancelled") {
      return {
        icon: <CircleX />,
        title: "已取消",
        subtitle: "本次没有写入任何数据",
      };
    }
    if (status === "expired") {
      return {
        icon: <Clock />,
        title: "已失效",
        subtitle: "该操作已处理或已过期",
      };
    }
    return {
      icon: <ClipboardCheck />,
      title: "待确认的训练记录",
      subtitle: request.message,
    };
  })();

  return (
    <Card className={terminal ? undefined : "border-brand/40"}>
      <CardHeader {...header} />
      <CardBody className="space-y-3">
        {terminal ? (
          <div className="space-y-1.5">
            {displayRows.map((row, i) => (
              <div
                key={`${row.name}-${i}`}
                className="flex items-center gap-2 rounded-lg border border-hairline bg-page px-2.5 py-1.5 text-sm"
              >
                <span className="min-w-0 flex-1 truncate text-ink">
                  {row.name}
                </span>
                <span className="shrink-0 text-xs text-ink-2 tabular">
                  {describe(row)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-1.5">
            {rows.map((row, i) => (
              <div
                key={`${row.name}-${i}`}
                className="rounded-lg border border-hairline bg-page px-2.5 py-2"
              >
                <div className="mb-1.5 truncate text-sm font-medium text-ink">
                  {row.name}
                </div>
                <div className="flex items-end gap-2">
                  <label className="min-w-0 flex-1">
                    <span className="mb-1 block text-xs text-ink-muted">
                      组数
                    </span>
                    <Input
                      type="number"
                      min={0}
                      step={1}
                      className="h-8 px-2 text-sm"
                      value={row.sets}
                      disabled={busy}
                      aria-label={`${row.name} 组数`}
                      onChange={(e) => updateRow(i, "sets", e.target.value)}
                    />
                  </label>
                  <span className="pb-2 text-xs text-ink-muted">×</span>
                  <label className="min-w-0 flex-1">
                    <span className="mb-1 block text-xs text-ink-muted">
                      次数
                    </span>
                    <Input
                      type="number"
                      min={0}
                      step={1}
                      className="h-8 px-2 text-sm"
                      value={row.reps}
                      disabled={busy}
                      aria-label={`${row.name} 次数`}
                      onChange={(e) => updateRow(i, "reps", e.target.value)}
                    />
                  </label>
                  <label className="min-w-0 flex-[1.2]">
                    <span className="mb-1 block text-xs text-ink-muted">
                      重量 kg
                    </span>
                    <Input
                      type="number"
                      min={0}
                      step={2.5}
                      className="h-8 px-2 text-sm"
                      value={row.weight_kg}
                      disabled={busy}
                      placeholder="自重"
                      aria-label={`${row.name} 重量`}
                      onChange={(e) =>
                        updateRow(i, "weight_kg", e.target.value)
                      }
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        )}

        {error ? (
          <div className="rounded-lg border border-delta-down/40 bg-delta-down/5 px-2.5 py-1.5 text-xs text-ink">
            {error}
          </div>
        ) : null}

        {finalText !== null ? (
          <div
            className={
              status === "confirmed"
                ? "flex items-center gap-1.5 text-xs text-delta-up"
                : "flex items-center gap-1.5 text-xs text-ink-2"
            }
          >
            {status === "confirmed" ? (
              <CircleCheck className="size-3.5" aria-hidden="true" />
            ) : status === "cancelled" ? (
              <CircleX className="size-3.5" aria-hidden="true" />
            ) : (
              <Clock className="size-3.5" aria-hidden="true" />
            )}
            <span>{finalText}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void submit("confirm")}
            >
              {submittingAction === "confirm" ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {submittingAction === "confirm" ? "写入中…" : "确认写入"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => void submit("cancel")}
            >
              {submittingAction === "cancel" ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {submittingAction === "cancel" ? "取消中…" : "取消"}
            </Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
