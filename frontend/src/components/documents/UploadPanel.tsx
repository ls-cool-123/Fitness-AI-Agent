import { BookOpen, FileText, Upload, X } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { uploadDocuments } from "@/lib/api";
import type { UploadResponse } from "@/lib/api";

/**
 * 知识库文档上传。
 *
 * 相比旧版表单少了「文档类型」下拉框 —— 它唯一的作用是过滤文件选择器，
 * 而 `<input accept>` 直接就能做到，多一个受控状态没有价值。
 *
 * 嵌入大文档可能要好几分钟（旧客户端给这个接口设了 6000s 超时）。fetch 默认
 * 不超时，所以这里只需要把按钮置灰、给个进行中的文案。
 */
export function UploadPanel() {
  const [collection, setCollection] = useState("fitness_kb");
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload() {
    if (!files.length || uploading) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const res = await uploadDocuments({ files, collectionName: collection });
      setResult(res);
      setFiles([]);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  return (
    <Card>
      <CardHeader
        icon={<BookOpen />}
        title="知识库上传"
        subtitle="上传 PDF / TXT / MD，Agent 回答时会引用它们"
      />
      <CardBody className="space-y-3">
        <Field label="集合名称">
          <Input
            value={collection}
            onChange={(e) => setCollection(e.target.value)}
          />
        </Field>

        <div>
          <span className="mb-1.5 block text-xs font-medium text-ink-2">选择文件</span>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.txt,.md"
            onChange={(e) => {
              setFiles(Array.from(e.target.files ?? []));
              setResult(null);
            }}
            className="block w-full cursor-pointer rounded-lg border border-dashed border-hairline bg-page px-3 py-2.5 text-xs text-ink-2 file:mr-3 file:cursor-pointer file:rounded-md file:border-0 file:bg-brand-soft file:px-2.5 file:py-1 file:text-xs file:font-medium file:text-brand"
          />
        </div>

        {files.length > 0 ? (
          <div className="space-y-1">
            {files.map((file) => (
              <div
                key={file.name}
                className="flex items-center gap-2 text-xs text-ink-2"
              >
                <FileText className="size-3.5 shrink-0 text-brand" />
                <span className="min-w-0 flex-1 truncate">{file.name}</span>
                <span className="shrink-0 tabular">
                  {(file.size / 1024).toFixed(0)} KB
                </span>
              </div>
            ))}
          </div>
        ) : null}

        <Button
          className="w-full"
          size="sm"
          disabled={!files.length || uploading}
          onClick={() => void upload()}
        >
          <Upload />
          {uploading ? "上传并嵌入中…" : "上传文档"}
        </Button>

        {result ? (
          <div className="space-y-1 border-t border-hairline pt-3">
            {result.files.map((f) => (
              <div key={f.filename} className="flex items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate text-ink-2">
                  {f.filename}
                </span>
                {/* 状态不靠颜色单独表达：同时有图标或文字 */}
                <span
                  className={
                    f.status === "success"
                      ? "shrink-0 text-delta-up"
                      : "shrink-0 text-delta-down"
                  }
                >
                  {f.status === "success" ? "已入库" : (f.reason ?? f.status)}
                </span>
              </div>
            ))}
          </div>
        ) : null}

        {error ? (
          <div className="flex items-start gap-1.5 text-xs text-delta-down">
            <X className="mt-0.5 size-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
