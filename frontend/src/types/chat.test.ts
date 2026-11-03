import { describe, expect, it } from "vitest";

import { isConfirmPlanInterrupt, isConfirmWorkoutInterrupt } from "./chat";

const valid = {
  id: "int-1",
  value: {
    action: "confirm_workout",
    message: "即将写入训练记录，请确认解析结果",
    preview: [
      {
        name: "深蹲",
        sets: 5,
        reps: 5,
        weight_kg: 80,
        set_details: null,
        notes: null,
      },
    ],
  },
  thread_id: "u-1:abc",
};

describe("isConfirmWorkoutInterrupt", () => {
  it("接受结构完整的 confirm_workout 载荷", () => {
    expect(isConfirmWorkoutInterrupt(valid)).toBe(true);
  });

  it("拒绝未知 action，交给以后的中断类型扩展", () => {
    expect(
      isConfirmWorkoutInterrupt({
        ...valid,
        value: { ...valid.value, action: "confirm_something_else" },
      }),
    ).toBe(false);
  });

  it("缺少线程 id 或 preview 字段类型不对时拒绝", () => {
    const withoutThread = { id: valid.id, value: valid.value };
    expect(isConfirmWorkoutInterrupt(withoutThread)).toBe(false);

    expect(
      isConfirmWorkoutInterrupt({
        ...valid,
        value: {
          ...valid.value,
          preview: [{ name: "深蹲", sets: "5" }],
        },
      }),
    ).toBe(false);
  });

  it("value 为 null（线程里没有待确认操作）时拒绝", () => {
    expect(isConfirmWorkoutInterrupt({ ...valid, value: null })).toBe(false);
  });
});

const planPreview = {
  name: "三分化 · 新手",
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

const validPlanInterrupt = {
  id: "int-2",
  value: {
    action: "confirm_plan",
    message: "即将生成训练计划",
    plan: planPreview,
  },
  thread_id: "u-1:abc",
};

describe("isConfirmPlanInterrupt", () => {
  it("接受结构完整的 confirm_plan 载荷", () => {
    expect(isConfirmPlanInterrupt(validPlanInterrupt)).toBe(true);
  });

  it("拒绝未知 action / 缺少 days / 动作字段类型错误", () => {
    expect(
      isConfirmPlanInterrupt({
        ...validPlanInterrupt,
        value: { ...validPlanInterrupt.value, action: "confirm_other" },
      }),
    ).toBe(false);
    expect(
      isConfirmPlanInterrupt({
        ...validPlanInterrupt,
        value: {
          ...validPlanInterrupt.value,
          plan: { ...planPreview, days: [] },
        },
      }),
    ).toBe(false);
    expect(
      isConfirmPlanInterrupt({
        ...validPlanInterrupt,
        value: {
          ...validPlanInterrupt.value,
          plan: {
            ...planPreview,
            days: [
              {
                ...planPreview.days[0],
                exercises: [
                  { ...planPreview.days[0].exercises[0], sets: "3" },
                ],
              },
            ],
          },
        },
      }),
    ).toBe(false);
  });

  it("缺少 thread_id 时拒绝（流式事件一定会带）", () => {
    const { id, value } = validPlanInterrupt;
    expect(isConfirmPlanInterrupt({ id, value })).toBe(false);
  });
});
