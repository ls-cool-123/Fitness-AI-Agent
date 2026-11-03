/**
 * 3D 人体模型与训练肌群的映射。
 *
 * `body.glb` 的每个 mesh 在 `userData` 里带英文解剖名（如
 * "Clavicular head of pectoralis major muscle"）。这里用一组**顺序敏感**的
 * 正则把它归到 10 个训练肌群之一。
 *
 * 顺序很重要：腘绳肌的 "Biceps femoris" 含 "biceps"，必须排在二头之前，
 * 否则会被误归到肱二头肌。
 */

import type { MuscleGroupId } from "@/types/plan";

export interface MuscleGroupMeta {
  name: string;
  color: string;
  patterns: RegExp[];
}

export const MUSCLE_GROUP_META: Record<MuscleGroupId, MuscleGroupMeta> = {
  chest: {
    name: "胸",
    color: "#ff6a2b",
    patterns: [/pectoralis/i],
  },
  back: {
    name: "背",
    color: "#2a78d6",
    patterns: [
      /latissimus/i,
      /rhomboid/i,
      /erector spinae/i,
      /iliocostalis/i,
      /longissimus/i,
      /spinalis/i,
      /trapezius/i,
      /levator scapulae/i,
      /serratus posterior/i,
    ],
  },
  shoulders: {
    name: "肩",
    color: "#ffb000",
    patterns: [
      /deltoid/i,
      /supraspinatus/i,
      /infraspinatus/i,
      /teres major/i,
      /teres minor/i,
      /subscapularis/i,
    ],
  },
  hamstrings: {
    name: "腘绳肌",
    color: "#7c5cff",
    patterns: [/biceps femoris/i, /semitendinosus/i, /semimembranosus/i],
  },
  biceps: {
    name: "二头",
    color: "#00a6a6",
    patterns: [/biceps brachii/i, /brachialis/i],
  },
  triceps: {
    name: "三头",
    color: "#e5484d",
    patterns: [/triceps brachii/i],
  },
  quads: {
    name: "股四头",
    color: "#4caf50",
    patterns: [/rectus femoris/i, /vastus/i],
  },
  glutes: {
    name: "臀",
    color: "#b45cf0",
    patterns: [/gluteus/i],
  },
  calves: {
    name: "小腿",
    color: "#00b8d9",
    patterns: [/gastrocnemius/i, /soleus/i, /tibialis anterior/i],
  },
  core: {
    name: "核心",
    color: "#f2c94c",
    patterns: [
      /rectus abdominis/i,
      /external abdominal oblique/i,
      /internal abdominal oblique/i,
      /transversus abdominis/i,
    ],
  },
};

const ORDERED_GROUPS = Object.entries(MUSCLE_GROUP_META) as [
  MuscleGroupId,
  MuscleGroupMeta,
][];

/** 把模型里的英文解剖名归到训练肌群；识别不了返回 null。 */
export function groupForMuscle(anatomyName: string): MuscleGroupId | null {
  const name = anatomyName.trim();
  if (!name) return null;
  for (const [id, meta] of ORDERED_GROUPS) {
    if (meta.patterns.some((pattern) => pattern.test(name))) return id;
  }
  return null;
}

/** 没有接口数据时也要能给 3D 列表一个中文名。 */
export function muscleGroupName(id: MuscleGroupId): string {
  return MUSCLE_GROUP_META[id].name;
}
