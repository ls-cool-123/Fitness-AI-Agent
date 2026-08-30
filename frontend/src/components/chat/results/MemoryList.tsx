import { Brain } from "lucide-react";

import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { MemoryItem } from "@/types/tools";

/** recall_memories_tool 召回的长期记忆。 */
export function MemoryList({ memories }: { memories: MemoryItem[] }) {
  return (
    <Card>
      <CardHeader
        icon={<Brain />}
        title="关于你的记忆"
        subtitle={`召回 ${memories.length} 条`}
      />
      <CardBody className="space-y-2">
        {memories.map((memory, i) => (
          <div
            key={`${memory.timestamp}-${i}`}
            className="rounded-lg border border-hairline bg-page px-3 py-2.5"
          >
            <p className="text-sm text-ink">{memory.content}</p>
            <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 text-xs text-ink-muted">
              <span className="rounded-full bg-brand-soft px-2 py-0.5 font-medium text-brand">
                {memory.category || memory.memory_type}
              </span>
              <span className="tabular">{memory.timestamp.slice(0, 10)}</span>
            </div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
