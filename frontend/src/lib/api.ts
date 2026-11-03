import { readNdjson } from "@/lib/stream";
import type { StreamEvent } from "@/lib/stream";
import type { ConfirmEditPayload, ConfirmResponse } from "@/types/chat";
import type {
  PlanGenerateRequest,
  PlanMuscleCatalog,
  PlanSummary,
  PlanSwap,
  TrainingPlan,
} from "@/types/plan";
import {
  isPlanMuscleCatalog,
  isPlanSummary,
  isTrainingPlan,
} from "@/types/plan";
import type { WorkoutSessionDto } from "@/types/tools";

/**
 * 后端 API 客户端。
 *
 * 不需要 base_url：开发时 Vite 代理、生产时 nginx 都把 /chat、/workout、
 * /documents 转发给 FastAPI，前端始终同源请求，所以路径直接写相对地址。
 */

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/** 训练动作，字段与后端 ExerciseItem 一一对应。 */
export interface ExercisePayload {
  name: string;
  sets: number;
  reps: number;
  weight_kg: number;
  set_details: { reps: number; weight_kg: number }[] | null;
  notes: string | null;
}

export interface AddWorkoutResponse {
  status: string;
  session_id: string | null;
  parsed: Record<string, unknown>[];
  message: string;
}

export interface ProgressResponse {
  /** analyze_progress_tool 的原始输出，两种模式的 key 集不同，需要类型守卫分派。 */
  analysis: Record<string, unknown>;
  series: { date: string; max_weight_kg: number; volume_kg: number }[];
}

export interface CategorySummaryResponse {
  categories: { category: string; total_volume_kg: number; total_sessions: number }[];
}

export interface UploadResponse {
  status: string;
  collection: string;
  files: { filename: string; status: string; reason?: string }[];
}

/** 把非 2xx 响应转成带后端 detail 的错误，便于界面直接显示原因。 */
async function ensureOk(res: Response): Promise<Response> {
  if (res.ok) return res;

  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // 响应体不是 JSON（如网关返回的 HTML 错误页），保留状态码文案
  }
  throw new Error(detail);
}

/**
 * 流式聊天。
 *
 * **必须每轮都发全量历史。** 后端 _build_agent_input 靠「checkpointer 线程是否
 * 为空」来决定用哪条路径：线程有历史就只取最新一条用户消息（避免消息数按 O(N²)
 * 膨胀）；线程为空（首轮，或进程重启后 MemorySaver 的内存态丢了）就用这里发过去
 * 的历史重建对话。所以不要"优化"成只发最后一条——那样后端重启后上下文会整段丢失。
 */
export async function* chatStream(params: {
  messages: ChatMessage[];
  userId: string;
  /** 本次对话的线程 id；同一用户的不同会话必须传不同值，否则会共享上下文。 */
  conversationId: string;
  collectionName?: string;
  signal?: AbortSignal;
}): AsyncGenerator<StreamEvent> {
  const res = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: params.messages,
      user_id: params.userId,
      conversation_id: params.conversationId,
      collection_name: params.collectionName ?? "fitness_kb",
    }),
    signal: params.signal,
  });

  await ensureOk(res);
  yield* readNdjson(res);
}

/**
 * 409 的专用错误类型。
 *
 * 「线程没有待确认操作」是正常的业务分支（重复点击、过期、或者别处已经处理过），
 * 不该走页面顶部的「请求失败」提示，而应让确认卡片自己进入失效终态。
 */
export class ConfirmConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfirmConflictError";
  }
}

/**
 * 确认或取消挂起的训练记录写入。
 *
 * edits 是确认卡片里的当前数值（用户没改的行也会原样回传）；取消时不传。
 * 后端仍允许省略 edits，此时沿用 Agent 解析的原值。
 */
export async function confirmChat(params: {
  userId: string;
  conversationId: string;
  approved: boolean;
  edits?: ConfirmEditPayload[];
  signal?: AbortSignal;
}): Promise<ConfirmResponse> {
  const res = await fetch("/chat/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: params.userId,
      conversation_id: params.conversationId,
      approved: params.approved,
      ...(params.edits ? { edits: params.edits } : {}),
    }),
    signal: params.signal,
  });

  if (res.status === 409) {
    let detail = "该操作已处理或已过期";
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // 409 的 body 不是 JSON 时用上面的默认文案，不影响进入失效终态
    }
    throw new ConfirmConflictError(detail);
  }

  await ensureOk(res);
  return res.json();
}

export async function addWorkout(
  userId: string,
  exercises: ExercisePayload[],
): Promise<AddWorkoutResponse> {
  const res = await fetch("/workout/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, exercises }),
  });
  await ensureOk(res);
  return res.json();
}

export async function fetchHistory(params: {
  userId: string;
  exerciseName?: string;
  daysBack?: number;
  limit?: number;
  signal?: AbortSignal;
}): Promise<WorkoutSessionDto[]> {
  const query = new URLSearchParams({ user_id: params.userId });
  if (params.exerciseName) query.set("exercise_name", params.exerciseName);
  if (params.daysBack) query.set("days_back", String(params.daysBack));
  if (params.limit) query.set("limit", String(params.limit));

  const res = await fetch(`/workout/history?${query}`, { signal: params.signal });
  await ensureOk(res);
  const body = await res.json();
  return body.sessions ?? [];
}

export async function fetchProgress(params: {
  userId: string;
  exerciseName?: string;
  category?: string;
  daysBack?: number;
  signal?: AbortSignal;
}): Promise<ProgressResponse> {
  const query = new URLSearchParams({ user_id: params.userId });
  if (params.exerciseName) query.set("exercise_name", params.exerciseName);
  if (params.category) query.set("category", params.category);
  if (params.daysBack) query.set("days_back", String(params.daysBack));

  const res = await fetch(`/workout/progress?${query}`, { signal: params.signal });
  await ensureOk(res);
  return res.json();
}

export async function fetchCategorySummary(params: {
  userId: string;
  daysBack?: number;
  signal?: AbortSignal;
}): Promise<CategorySummaryResponse> {
  const query = new URLSearchParams({ user_id: params.userId });
  if (params.daysBack) query.set("days_back", String(params.daysBack));

  const res = await fetch(`/workout/category-summary?${query}`, {
    signal: params.signal,
  });
  await ensureOk(res);
  return res.json();
}

export async function uploadDocuments(params: {
  files: File[];
  collectionName?: string;
  category?: string;
}): Promise<UploadResponse> {
  const form = new FormData();
  for (const file of params.files) form.append("files", file);

  const query = new URLSearchParams({
    collection_name: params.collectionName ?? "fitness_kb",
    category: params.category ?? "general",
  });

  const res = await fetch(`/documents/upload?${query}`, {
    method: "POST",
    body: form,
  });
  await ensureOk(res);
  return res.json();
}

// ---------------------------------------------------------------------------
// 训练计划
// ---------------------------------------------------------------------------

/** 从 `{plan: ...}` 响应里取出经过守卫校验的计划。 */
function readPlan(body: unknown): TrainingPlan {
  if (
    typeof body === "object" &&
    body !== null &&
    "plan" in body &&
    isTrainingPlan((body as { plan: unknown }).plan)
  ) {
    return (body as { plan: TrainingPlan }).plan;
  }
  throw new Error("训练计划数据格式异常");
}

export async function fetchPlanMuscles(
  signal?: AbortSignal,
): Promise<PlanMuscleCatalog> {
  const res = await fetch("/plan/muscles", { signal });
  await ensureOk(res);
  const body = await res.json();
  if (!isPlanMuscleCatalog(body)) throw new Error("肌群动作数据格式异常");
  return body;
}

export async function generatePlan(params: PlanGenerateRequest): Promise<TrainingPlan> {
  const res = await fetch("/plan/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  await ensureOk(res);
  return readPlan(await res.json());
}

export async function fetchPlans(
  userId: string,
  limit = 20,
  signal?: AbortSignal,
): Promise<PlanSummary[]> {
  const query = new URLSearchParams({ user_id: userId, limit: String(limit) });
  const res = await fetch(`/plan/list?${query}`, { signal });
  await ensureOk(res);
  const body = await res.json();
  if (
    typeof body !== "object" ||
    body === null ||
    !Array.isArray((body as { plans?: unknown }).plans)
  ) {
    throw new Error("计划列表数据格式异常");
  }
  return (body as { plans: unknown[] }).plans.filter(isPlanSummary);
}

export async function fetchPlan(
  userId: string,
  planId: string,
  signal?: AbortSignal,
): Promise<TrainingPlan> {
  const query = new URLSearchParams({ user_id: userId });
  const res = await fetch(
    `/plan/${encodeURIComponent(planId)}?${query}`,
    { signal },
  );
  await ensureOk(res);
  return readPlan(await res.json());
}

export async function swapPlanExercises(params: {
  userId: string;
  planId: string;
  swaps: PlanSwap[];
}): Promise<TrainingPlan> {
  const res = await fetch(`/plan/${encodeURIComponent(params.planId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: params.userId, swaps: params.swaps }),
  });
  await ensureOk(res);
  return readPlan(await res.json());
}

export async function deletePlan(userId: string, planId: string): Promise<void> {
  const query = new URLSearchParams({ user_id: userId });
  const res = await fetch(
    `/plan/${encodeURIComponent(planId)}?${query}`,
    { method: "DELETE" },
  );
  await ensureOk(res);
}
