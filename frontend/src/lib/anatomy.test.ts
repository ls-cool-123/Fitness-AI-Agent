import { describe, expect, it } from "vitest";

import { groupForMuscle } from "./anatomy";

describe("groupForMuscle", () => {
  it("把常见解剖名归到训练肌群", () => {
    expect(groupForMuscle("Clavicular head of pectoralis major muscle")).toBe("chest");
    expect(groupForMuscle("Latissimus dorsi muscle.002")).toBe("back");
    expect(groupForMuscle("Acromial part of deltoid muscle")).toBe("shoulders");
    expect(groupForMuscle("Long head of biceps brachii")).toBe("biceps");
    expect(groupForMuscle("Lateral head of triceps brachii")).toBe("triceps");
    expect(groupForMuscle("Rectus femoris muscle")).toBe("quads");
    expect(groupForMuscle("Gluteus maximus muscle.002")).toBe("glutes");
    expect(groupForMuscle("Lateral head of gastrocnemius")).toBe("calves");
    expect(groupForMuscle("Rectus abdominis muscle")).toBe("core");
  });

  it("腘绳肌的 Biceps femoris 不能被归成二头", () => {
    expect(groupForMuscle("Long head of biceps femoris")).toBe("hamstrings");
    expect(groupForMuscle("Semitendinosus muscle")).toBe("hamstrings");
  });

  it("识别不了的返回 null", () => {
    expect(groupForMuscle("Frontalis muscle")).toBeNull();
    expect(groupForMuscle("")).toBeNull();
  });
});
