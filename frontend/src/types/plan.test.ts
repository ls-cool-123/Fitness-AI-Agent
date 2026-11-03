import { describe, expect, it } from "vitest";

import {
  isPlanMuscleCatalog,
  isPlanPreview,
  isPlanToolResult,
  isTrainingPlan,
} from "./plan";
import type { PlanPreview, TrainingPlan } from "./plan";

const preview: PlanPreview = {
  name: "三分化 · 新手 · 胸重点",
  experience: "beginner",
  split: "three_day",
  goal: "增肌",
  focus_muscles: ["胸"],
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

const plan: TrainingPlan = {
  ...preview,
  version: 1,
  plan_id: "plan-1",
  source: "anatomy",
  created_at: "2026-10-26T00:00:00Z",
};

describe("plan guards", () => {
  it("接受完整的 preview / 已保存计划", () => {
    expect(isPlanPreview(preview)).toBe(true);
    expect(isTrainingPlan(plan)).toBe(true);
  });

  it("拒绝缺少 days 或动作字段类型错误的计划", () => {
    expect(isPlanPreview({ ...preview, days: [] })).toBe(false);
    expect(
      isPlanPreview({
        ...preview,
        days: [
          {
            ...preview.days[0],
            exercises: [{ ...preview.days[0].exercises[0], sets: "3" }],
          },
        ],
      }),
    ).toBe(false);
  });

  it("已保存计划必须有 plan_id/source/created_at", () => {
    expect(isTrainingPlan({ ...preview })).toBe(false);
    expect(isTrainingPlan({ ...plan, plan_id: undefined })).toBe(false);
  });

  it("识别计划工具的成功返回", () => {
    expect(
      isPlanToolResult({ status: "saved", plan_id: "plan-1", plan }),
    ).toBe(true);
    expect(
      isPlanToolResult({ status: "needs_info", missing: ["experience"], question: "?" }),
    ).toBe(true);
    expect(isPlanToolResult({ status: "saved", plan_id: "plan-1" })).toBe(false);
  });

  it("校验肌群动作目录", () => {
    expect(
      isPlanMuscleCatalog({
        groups: [
          {
            id: "chest",
            name: "胸",
            description: "胸大肌",
            exercises: {
              beginner: [
                {
                  name: "器械推胸",
                  equipment: "器械",
                  is_compound: true,
                  default_sets: 3,
                  default_reps: "8-12",
                  rest_seconds: 90,
                  description: "固定轨迹",
                },
              ],
              experienced: [],
            },
          },
        ],
      }),
    ).toBe(true);
    expect(isPlanMuscleCatalog({ groups: [{ id: "unknown" }] })).toBe(false);
  });
});
