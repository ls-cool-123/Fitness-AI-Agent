/**
 * 聊天协议里「需要人工确认」那一层的类型建模。
 *
 * 后端 interrupt() 的载荷不是一个稳定的信封：`value` 是工具自己决定的任意 JSON，
 * 只有 `action` 可以可靠判别。这里照 types/tools.ts 的做法，把前端认得的 action
 * 单独建模并配类型守卫——未知 action 直接挡在卡片外面，后端以后加新的中断类型
 * 时前端不会因为访问了不存在的字段而崩。
 */

import type { PlanPreview } from "@/types/plan";
import { isPlanPreview } from "@/types/plan";
import type { SetDetail } from "@/types/tools";

/** 确认卡片的生命周期。终态（confirmed/cancelled/expired）不可再操作。 */
export type ConfirmStatus =
  | "pending"
  | "submitting"
  | "confirmed"
  | "cancelled"
  | "expired";

/**
 * Agent 解析出、准备写入的单条动作，字段对应后端 ParsedExercise.model_dump()。
 *
 * sets/reps/weight_kg 都允许为 null：有氧类动作只记时长，没有组数和重量。
 */
export interface WorkoutPreviewItem {
  name: string;
  sets: number | null;
  /** 总次数（所有组之和），与工具入参一致。 */
  reps: number | null;
  /** 每组次数（reps / sets），卡片优先用它展示与编辑；无组数时为 null。 */
  reps_per_set?: number | null;
  weight_kg: number | null;
  set_details: SetDetail[] | null;
  notes: string | null;
}

/** 写库前的人工确认请求。action 是唯一可靠的判别字段。 */
export interface ConfirmWorkoutInterruptValue {
  action: "confirm_workout";
  message: string;
  preview: WorkoutPreviewItem[];
}

/** 训练计划保存前的人工确认请求。mode 区分新建/修改，仅影响按钮文案。 */
export interface ConfirmPlanInterruptValue {
  action: "confirm_plan";
  message: string;
  mode?: "create" | "update";
  plan: PlanPreview;
}

/**
 * 已知中断 action 的联合类型。
 *
 * 目前有「确认写入训练记录」和「确认生成训练计划」两种；以后新增 action 时
 * 在这里加成员并补守卫，下游卡片分派沿用同一套思路。
 */
export type InterruptValue =
  | ConfirmWorkoutInterruptValue
  | ConfirmPlanInterruptValue;

/**
 * 中断载荷的信封：流式事件的 data，以及 /chat/confirm 响应里的 interrupt 字段。
 *
 * `value` 的形状由 action 决定，这里用联合类型收口。thread_id 只有流式事件一定
 * 带（后端在流结束后补上）；/chat/confirm 里可能出现的二次中断没有它。
 */
export interface InterruptPayload<T = InterruptValue | null> {
  id: string | null;
  value: T;
  /** LangGraph 线程 id，形如 "u-1:abc"。仅用于排查，前端不拿它拼请求。 */
  thread_id?: string;
}

/**
 * 确认卡片回传的修正值。
 *
 * 核心字段与后端 build_workout 的入参对齐（name 必填 + 三个可改数值）。卡片上
 * 没改过的行会把原条目的 set_details / notes 一并带回，避免一次确认把它们丢掉。
 */
export interface ConfirmEdit {
  name: string;
  sets: number | null;
  /** 总次数；给了 reps_per_set 时后端会以它为准重算。 */
  reps: number | null;
  /** 卡片上编辑的是每组次数，原样回传，避免"总次数 vs 每组次数"的歧义。 */
  reps_per_set?: number | null;
  weight_kg: number | null;
  set_details?: SetDetail[] | null;
  notes?: string | null;
}

/** 训练计划确认卡片回传的换动作/删除动作项。后端按 slot_id 定位。 */
export interface PlanEdit {
  slot_id: string;
  /** 换动作时必填；remove=true 时可不填。 */
  exercise_name?: string;
  /** 从计划中删除这个 slot。 */
  remove?: boolean;
}

/** /chat/confirm 的 edits 可能是训练记录数值，也可能是计划换动作。 */
export type ConfirmEditPayload = ConfirmEdit | PlanEdit;

/** POST /chat/confirm 的响应。interrupt 非空表示又出现了一个待确认操作。 */
export interface ConfirmResponse {
  answer: string;
  interrupt: InterruptPayload | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 数值字段可能缺省 / 为 null，也必须排除 NaN / Infinity 这类 JSON 里不会出现的值。 */
function isNullableNumber(value: unknown): value is number | null {
  return value == null || (typeof value === "number" && Number.isFinite(value));
}

export function isWorkoutPreviewItem(
  value: unknown,
): value is WorkoutPreviewItem {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    isNullableNumber(value.sets) &&
    isNullableNumber(value.reps) &&
    isNullableNumber(value.reps_per_set ?? null) &&
    isNullableNumber(value.weight_kg) &&
    (value.notes == null || typeof value.notes === "string") &&
    (value.set_details == null || Array.isArray(value.set_details))
  );
}

/**
 * 判别「确认写入训练记录」这一种中断。
 *
 * 校验到 preview 每一项而不只校验 action：卡片会直接渲染这些字段，缺一个就会在
 * 渲染期抛错，而 HITL 卡片崩掉会把整个对话线程卡死——宁可退化成不渲染卡片。
 */
export function isConfirmWorkoutInterrupt(
  value: unknown,
): value is InterruptPayload<ConfirmWorkoutInterruptValue> & {
  thread_id: string;
} {
  if (!isRecord(value)) return false;
  if (value.id != null && typeof value.id !== "string") return false;
  if (typeof value.thread_id !== "string") return false;

  const payload = value.value;
  return (
    isRecord(payload) &&
    payload.action === "confirm_workout" &&
    typeof payload.message === "string" &&
    Array.isArray(payload.preview) &&
    payload.preview.every(isWorkoutPreviewItem)
  );
}

/**
 * 判别「确认生成训练计划」这一种中断。
 *
 * 计划预览会直接渲染 days/exercises/alternatives，字段缺失同样会让卡片崩掉；
 * 因此用 types/plan.ts 的 isPlanPreview 做深度校验。
 */
export function isConfirmPlanInterrupt(
  value: unknown,
): value is InterruptPayload<ConfirmPlanInterruptValue> & {
  thread_id: string;
} {
  if (!isRecord(value)) return false;
  if (value.id != null && typeof value.id !== "string") return false;
  if (typeof value.thread_id !== "string") return false;

  const payload = value.value;
  return (
    isRecord(payload) &&
    payload.action === "confirm_plan" &&
    typeof payload.message === "string" &&
    (payload.mode == null ||
      payload.mode === "create" ||
      payload.mode === "update") &&
    isPlanPreview(payload.plan)
  );
}
