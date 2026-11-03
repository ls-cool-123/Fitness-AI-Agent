import type { PlanToolResult } from "@/types/plan";

/**
 * 工具输出的类型建模。
 *
 * 后端五个工具都返回 `json.dumps(...)` 字符串，但**没有统一的信封，也没有 kind
 * 判别字段**——同一个工具能返回好几套完全不同的 key 集。所以分派要两级：
 *
 * 1. 主判别用流事件里的 `tool` 名（可靠，来自 LangGraph 事件而非数据本身）
 * 2. 次级判别用 shape，即「哪个 key 存在」（区分同一工具的多套 schema）
 *
 * 这里把每套 shape 单独建模并配上类型守卫，让 tsc 在编译期就挡住「访问了这套
 * shape 里不存在的字段」这类运行时崩溃。
 */

// ---------------------------------------------------------------------------
// analyze_progress_tool —— 4 套 shape
// ---------------------------------------------------------------------------

/** 模式 1：单动作趋势分析。 */
export interface ProgressByExercise {
  exercise: string;
  period_days: number;
  total_sessions: number;
  sessions_per_week: number;
  latest_max_weight_kg: number;
  all_time_max_weight_kg: number;
  avg_max_weight_first_half_kg: number;
  avg_max_weight_second_half_kg: number;
  max_weight_change_pct: number;
  avg_volume_first_half: number;
  avg_volume_second_half: number;
  volume_change_pct: number;
  trend_direction: "up" | "down" | "stable";
}

/** 模式 2：按身体部位聚合统计。注意 key 集和模式 1 几乎不重叠。 */
export interface ProgressByCategory {
  category: string;
  period_days: number;
  total_sessions: number;
  sessions_per_week: number;
  total_exercises: number;
  exercises: string[];
  total_sets: number;
  total_reps: number;
  total_volume_kg: number;
}

/** 两种模式各自的空结果 —— 只有 message 是共同的可用字段。 */
export interface ProgressEmpty {
  message: string;
  total_sessions: 0;
  exercise?: string;
  category?: string;
}

export type ProgressResult =
  | ProgressByExercise
  | ProgressByCategory
  | ProgressEmpty;

// ---------------------------------------------------------------------------
// query_workout_tool —— 顶层是数组，3 层嵌套
// ---------------------------------------------------------------------------

/** 单组明细。add_workout 写入时 reps 与 weight_kg 按组一一对应。 */
export interface SetDetail {
  reps: number;
  weight_kg: number;
}

export interface WorkoutItemDto {
  exercise: string;
  sets: number | null;
  reps: number | null;
  weight_kg: number | null;
  set_details: SetDetail[] | null;
}

export interface WorkoutSessionDto {
  session_id: string;
  date: string;
  notes: string | null;
  items: WorkoutItemDto[];
}

// ---------------------------------------------------------------------------
// rag_search_tool —— 数组 或 两种 object
// ---------------------------------------------------------------------------

export interface RagChunk {
  index: number;
  content: string;
  source: string;
  category: string;
  score: number | null;
}

/** 全部候选都低于重排序阈值时返回这个，而不是空数组。 */
export interface RagNoRelevantInfo {
  status: "no_relevant_info";
  message: string;
  max_score: number;
  threshold: number;
}

export type RagResult = RagChunk[] | RagNoRelevantInfo | ToolError;

// ---------------------------------------------------------------------------
// recall_memories_tool —— 数组 或 两种 object
// ---------------------------------------------------------------------------

export interface MemoryItem {
  content: string;
  relevance: number;
  memory_type: string;
  category: string;
  timestamp: string;
}

export interface MemoryEmpty {
  status: "empty";
  memories: [];
  message: string;
}

export type MemoryResult = MemoryItem[] | MemoryEmpty | ToolError;

// ---------------------------------------------------------------------------
// 通用
// ---------------------------------------------------------------------------

/** 工具内部异常时的返回。rag_search 和 recall_memories 都会走这条。 */
export interface ToolError {
  error: string;
}

/** 工具结果的全集。解析失败时后端推 null。 */
export type ToolResult =
  | ProgressResult
  | WorkoutSessionDto[]
  | RagResult
  | MemoryResult
  | PlanToolResult
  | null;

// ---------------------------------------------------------------------------
// 类型守卫
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 模式 1 的判别键是 trend_direction —— 空结果虽然也带 exercise，但没有它。 */
export function isProgressByExercise(
  value: unknown,
): value is ProgressByExercise {
  return isRecord(value) && "exercise" in value && "trend_direction" in value;
}

/** 模式 2 的判别键是 exercises 数组 —— 空结果带 category 但没有它。 */
export function isProgressByCategory(
  value: unknown,
): value is ProgressByCategory {
  return isRecord(value) && "category" in value && "exercises" in value;
}

export function isProgressEmpty(value: unknown): value is ProgressEmpty {
  return isRecord(value) && "message" in value && !("exercises" in value);
}

export function isToolError(value: unknown): value is ToolError {
  return isRecord(value) && typeof value.error === "string";
}

export function isRagChunks(value: unknown): value is RagChunk[] {
  return Array.isArray(value) && value.every((c) => isRecord(c) && "content" in c);
}

export function isRagNoRelevantInfo(
  value: unknown,
): value is RagNoRelevantInfo {
  return isRecord(value) && value.status === "no_relevant_info";
}

export function isMemoryItems(value: unknown): value is MemoryItem[] {
  return (
    Array.isArray(value) && value.every((m) => isRecord(m) && "relevance" in m)
  );
}

export function isMemoryEmpty(value: unknown): value is MemoryEmpty {
  return isRecord(value) && value.status === "empty";
}

export function isWorkoutSessions(value: unknown): value is WorkoutSessionDto[] {
  return Array.isArray(value) && value.every((s) => isRecord(s) && "items" in s);
}
