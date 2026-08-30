import { Inbox } from "lucide-react";

import type { ToolResult } from "@/types/tools";
import {
  isMemoryItems,
  isProgressByCategory,
  isProgressByExercise,
  isProgressEmpty,
  isRagChunks,
  isRagNoRelevantInfo,
  isToolError,
  isWorkoutSessions,
} from "@/types/tools";

import { CategoryCard } from "./CategoryCard";
import { MemoryList } from "./MemoryList";
import { ProgressCard } from "./ProgressCard";
import { RagSources } from "./RagSources";
import { WorkoutTable } from "./WorkoutTable";

/** 查无结果时的一行轻提示 —— 不占一整张卡片，LLM 的文字回答才是主角。 */
function EmptyHint({ msg }: { msg?: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-hairline border-dashed px-3 py-2 text-xs text-ink-muted">
      <Inbox className="size-3.5 shrink-0" aria-hidden="true" />
      {msg ?? "这段时间还没有相关记录"}
    </div>
  );
}

/**
 * 工具结果卡片分派。
 *
 * 两级判别：**先看工具名**（来自 LangGraph 事件，可靠），**再看 shape**（同一个
 * 工具有好几套 key 集，见 types/tools.ts 的说明）。反过来只靠 shape 会误判——
 * 比如 rag_search 和 recall_memories 的空结果都是 `{status, message}`。
 *
 * 返回 null = 不渲染任何东西。三种情况：结果没解析成 JSON、工具报错、工具名不认识。
 * 这些场景下 LLM 的自然语言回答本身就够了，塞一个技术性卡片只会干扰阅读。
 */
export function ToolResultCard({
  tool,
  result,
}: {
  tool: string;
  result: ToolResult;
}) {
  if (result == null || isToolError(result)) return null;

  switch (tool) {
    case "analyze_progress_tool":
      if (isProgressByExercise(result)) return <ProgressCard data={result} />;
      if (isProgressByCategory(result)) return <CategoryCard data={result} />;
      if (isProgressEmpty(result)) return <EmptyHint msg={result.message} />;
      return null;

    case "query_workout_tool":
      if (!isWorkoutSessions(result)) return null;
      return result.length ? <WorkoutTable sessions={result} /> : <EmptyHint />;

    case "rag_search_tool":
      if (isRagChunks(result)) {
        return result.length ? <RagSources chunks={result} /> : null;
      }
      // 命中了但全部低于重排序阈值 —— 这时 LLM 会说「知识库里没有」，不必重复
      if (isRagNoRelevantInfo(result)) return null;
      return null;

    case "recall_memories_tool":
      if (!isMemoryItems(result)) return null;
      return result.length ? <MemoryList memories={result} /> : null;

    default:
      return null;
  }
}
