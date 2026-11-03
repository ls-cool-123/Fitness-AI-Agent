/**
 * 训练计划相关的前端类型与类型守卫。
 *
 * 后端有两套略有差别的载荷：
 * - `PlanPreview`：interrupt 确认卡片里的计划（还没有 plan_id/created_at/source）；
 * - `TrainingPlan`：已保存的计划（多出 plan_id/source/created_at）。
 *
 * 所有从网络/流事件拿到的 JSON 都先用守卫校验再渲染，避免一个后端字段变更导致
 * 整个消息列表崩掉——和 `types/tools.ts` 的分派思路一致。
 */

export const MUSCLE_GROUP_IDS = [
  "chest",
  "back",
  "shoulders",
  "biceps",
  "triceps",
  "quads",
  "glutes",
  "hamstrings",
  "calves",
  "core",
] as const;

export type MuscleGroupId = (typeof MUSCLE_GROUP_IDS)[number];

export type Experience = "beginner" | "experienced";
export type Split = "three_day" | "five_day";
export type PlanSource = "anatomy" | "chat" | string;

export interface PlanExercise {
  slot_id: string;
  name: string;
  muscle_group: string;
  sets: number;
  /** 次数是区间字符串，例如 "8-12" 或 "30-60 秒"。 */
  reps: string;
  rest_seconds: number;
  note: string | null;
  alternatives: string[];
}

export interface PlanDay {
  day: number;
  title: string;
  focus: string[];
  warmup: string;
  exercises: PlanExercise[];
}

export interface PlanPreview {
  name: string;
  experience: Experience;
  split: Split;
  goal: string;
  focus_muscles: string[];
  days: PlanDay[];
  warnings: string[];
}

export interface TrainingPlan extends PlanPreview {
  version: number;
  plan_id: string;
  source: PlanSource;
  created_at: string;
}

export interface PlanSummary {
  plan_id: string;
  name: string;
  experience: string;
  split: string;
  source: string;
  created_at: string;
  day_count: number;
  focus_muscles: string[];
}

export interface MuscleExerciseOption {
  name: string;
  equipment: string;
  is_compound: boolean;
  default_sets: number;
  default_reps: string;
  rest_seconds: number;
  description: string;
}

export interface PlanMuscleGroup {
  id: MuscleGroupId;
  name: string;
  description: string;
  exercises: {
    beginner: MuscleExerciseOption[];
    experienced: MuscleExerciseOption[];
  };
}

export interface PlanMuscleCatalog {
  groups: PlanMuscleGroup[];
}

export interface PlanGenerateRequest {
  user_id: string;
  experience: Experience;
  split: Split;
  focus_muscles?: string[];
  preferred_exercises?: string[];
  day_focus?: string[] | null;
  goal?: string;
  plan_name?: string | null;
}

export interface PlanSwap {
  slot_id: string;
  exercise_name: string;
}

/** `create_training_plan_tool` 的返回值；错误形状由通用 ToolError 覆盖。 */
export type PlanToolResult =
  | { status: "saved"; plan_id: string; plan: TrainingPlan; message?: string }
  | { status: "cancelled"; message: string }
  | { status: "needs_info"; missing: string[]; question: string; message?: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isNonNegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

export function isMuscleGroupId(value: unknown): value is MuscleGroupId {
  return typeof value === "string" && (MUSCLE_GROUP_IDS as readonly string[]).includes(value);
}

export function isPlanExercise(value: unknown): value is PlanExercise {
  return (
    isRecord(value) &&
    typeof value.slot_id === "string" &&
    typeof value.name === "string" &&
    typeof value.muscle_group === "string" &&
    isNonNegativeNumber(value.sets) &&
    typeof value.reps === "string" &&
    isNonNegativeNumber(value.rest_seconds) &&
    (value.note == null || typeof value.note === "string") &&
    isStringArray(value.alternatives)
  );
}

export function isPlanDay(value: unknown): value is PlanDay {
  return (
    isRecord(value) &&
    isNonNegativeNumber(value.day) &&
    typeof value.title === "string" &&
    isStringArray(value.focus) &&
    typeof value.warmup === "string" &&
    Array.isArray(value.exercises) &&
    value.exercises.every(isPlanExercise)
  );
}

export function isPlanPreview(value: unknown): value is PlanPreview {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    (value.experience === "beginner" || value.experience === "experienced") &&
    (value.split === "three_day" || value.split === "five_day") &&
    typeof value.goal === "string" &&
    isStringArray(value.focus_muscles) &&
    Array.isArray(value.days) &&
    value.days.length > 0 &&
    value.days.every(isPlanDay) &&
    isStringArray(value.warnings)
  );
}

export function isTrainingPlan(value: unknown): value is TrainingPlan {
  return (
    isPlanPreview(value) &&
    isRecord(value) &&
    isNonNegativeNumber(value.version) &&
    typeof value.plan_id === "string" &&
    typeof value.source === "string" &&
    typeof value.created_at === "string"
  );
}

function isExerciseOption(value: unknown): value is MuscleExerciseOption {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    typeof value.equipment === "string" &&
    typeof value.is_compound === "boolean" &&
    isNonNegativeNumber(value.default_sets) &&
    typeof value.default_reps === "string" &&
    isNonNegativeNumber(value.rest_seconds) &&
    typeof value.description === "string"
  );
}

export function isPlanMuscleGroup(value: unknown): value is PlanMuscleGroup {
  if (!isRecord(value) || !isMuscleGroupId(value.id)) return false;
  if (typeof value.name !== "string" || typeof value.description !== "string") return false;
  const exercises = value.exercises;
  return (
    isRecord(exercises) &&
    Array.isArray(exercises.beginner) &&
    exercises.beginner.every(isExerciseOption) &&
    Array.isArray(exercises.experienced) &&
    exercises.experienced.every(isExerciseOption)
  );
}

export function isPlanMuscleCatalog(value: unknown): value is PlanMuscleCatalog {
  return (
    isRecord(value) &&
    Array.isArray(value.groups) &&
    value.groups.length > 0 &&
    value.groups.every(isPlanMuscleGroup)
  );
}

export function isPlanSummary(value: unknown): value is PlanSummary {
  return (
    isRecord(value) &&
    typeof value.plan_id === "string" &&
    typeof value.name === "string" &&
    typeof value.experience === "string" &&
    typeof value.split === "string" &&
    typeof value.source === "string" &&
    typeof value.created_at === "string" &&
    isNonNegativeNumber(value.day_count) &&
    isStringArray(value.focus_muscles)
  );
}

/**
 * 判别计划工具的返回。
 *
 * `needs_info` / `cancelled` 也返回 true，但调用方只在 `saved` 时渲染计划卡片；
 * 这两种状态让 LLM 用文字继续追问/告知即可。
 */
export function isPlanToolResult(value: unknown): value is PlanToolResult {
  if (!isRecord(value)) return false;
  if (value.status === "saved") {
    return typeof value.plan_id === "string" && isTrainingPlan(value.plan);
  }
  if (value.status === "cancelled") {
    return typeof value.message === "string";
  }
  if (value.status === "needs_info") {
    return isStringArray(value.missing) && typeof value.question === "string";
  }
  return false;
}
