import { BookOpen } from "lucide-react";

import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { RagChunk } from "@/types/tools";

/**
 * rag_search_tool 的来源引用。
 *
 * `content` 已经被后端 `_shrink` 截断到 ~300 字符 —— 这里只作为「答案出处」展示，
 * 完整内容由 LLM 的回答本身承载，不需要在前端再放全文。
 */
export function RagSources({ chunks }: { chunks: RagChunk[] }) {
  return (
    <Card>
      <CardHeader
        icon={<BookOpen />}
        title="参考资料"
        subtitle={`来自知识库的 ${chunks.length} 段内容`}
      />
      <CardBody className="space-y-2">
        {chunks.map((chunk) => (
          <div
            key={chunk.index}
            className="rounded-lg border border-hairline bg-page px-3 py-2.5"
          >
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span className="truncate text-xs font-medium text-ink-2">
                {chunk.source}
                {chunk.category ? (
                  <span className="ml-1.5 font-normal text-ink-muted">
                    · {chunk.category}
                  </span>
                ) : null}
              </span>
              {chunk.score != null ? (
                <span className="shrink-0 text-xs text-ink-muted tabular">
                  相关度 {chunk.score.toFixed(2)}
                </span>
              ) : null}
            </div>
            <p className="text-xs leading-relaxed text-ink-2">{chunk.content}</p>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
