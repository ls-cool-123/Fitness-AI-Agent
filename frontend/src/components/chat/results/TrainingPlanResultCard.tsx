import { TrainingPlanCard } from "@/components/plan/TrainingPlanCard";
import type { TrainingPlan } from "@/types/plan";

/** `create_training_plan_tool` 成功返回时嵌在聊天里的计划卡。 */
export function TrainingPlanResultCard({ plan }: { plan: TrainingPlan }) {
  return <TrainingPlanCard plan={plan} />;
}
