import { afterEach, describe, expect, it, vi } from "vitest";

import {
  chatStream,
  ConfirmConflictError,
  confirmChat,
  generatePlan,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** 包一个 NDJSON 响应，避免测试依赖真实后端。 */
function ndjson(lines: string[]): Response {
  return new Response(lines.join(""));
}

describe("chatStream", () => {
  it("请求体携带 conversation_id，并把流事件交给调用方", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body.conversation_id).toBe("conv-1");
      expect(body.user_id).toBe("u-1");
      return ndjson(['{"type":"status","data":"完成"}\n']);
    });
    vi.stubGlobal("fetch", fetchMock);

    const events = [];
    for await (const event of chatStream({
      messages: [{ role: "user", content: "你好" }],
      userId: "u-1",
      conversationId: "conv-1",
    })) {
      events.push(event);
    }

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/stream",
      expect.objectContaining({ method: "POST" }),
    );
    expect(events).toEqual([{ type: "status", data: "完成" }]);
  });
});

describe("confirmChat", () => {
  it("确认时回传 edits，并解析 answer", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body).toMatchObject({
        user_id: "u-1",
        conversation_id: "conv-1",
        approved: true,
      });
      expect(body.edits).toEqual([
        { name: "深蹲", sets: 5, reps: 5, weight_kg: 80 },
      ]);
      return new Response(
        JSON.stringify({ answer: "已记录", interrupt: null }),
        { headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const res = await confirmChat({
      userId: "u-1",
      conversationId: "conv-1",
      approved: true,
      edits: [{ name: "深蹲", sets: 5, reps: 5, weight_kg: 80 }],
    });

    expect(res).toEqual({ answer: "已记录", interrupt: null });
  });

  it("取消时不带 edits", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body.approved).toBe(false);
      expect("edits" in body).toBe(false);
      return new Response(
        JSON.stringify({ answer: "已取消", interrupt: null }),
        { headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await confirmChat({
      userId: "u-1",
      conversationId: "conv-1",
      approved: false,
    });
  });

  it("409 抛 ConfirmConflictError，而不是普通 Error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ detail: "当前对话没有待确认的操作" }),
          {
            status: 409,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
    );

    await expect(
      confirmChat({
        userId: "u-1",
        conversationId: "conv-1",
        approved: true,
      }),
    ).rejects.toBeInstanceOf(ConfirmConflictError);
  });
});

describe("generatePlan", () => {
  const plan = {
    version: 1,
    plan_id: "plan-1",
    name: "三分化 · 新手",
    experience: "beginner",
    split: "three_day",
    goal: "增肌",
    focus_muscles: ["胸"],
    source: "anatomy",
    created_at: "2026-10-26T00:00:00Z",
    warnings: [],
    days: [
      {
        day: 1,
        title: "推日",
        focus: ["胸", "肩", "三头"],
        warmup: "动态热身",
        exercises: [
          {
            slot_id: "d1e1",
            name: "器械推胸",
            muscle_group: "胸",
            sets: 3,
            reps: "8-12",
            rest_seconds: 90,
            note: null,
            alternatives: ["俯卧撑"],
          },
        ],
      },
    ],
  };

  it("提交经验/分化/重点肌群并返回计划", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body).toMatchObject({
        user_id: "u-1",
        experience: "beginner",
        split: "three_day",
        focus_muscles: ["胸"],
      });
      return new Response(JSON.stringify({ plan }), {
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await generatePlan({
      user_id: "u-1",
      experience: "beginner",
      split: "three_day",
      focus_muscles: ["胸"],
    });

    expect(result.plan_id).toBe("plan-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/plan/generate",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
