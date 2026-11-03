"""训练计划 REST API。

两条入口共用这里的生成器/服务：
- 人体图页面直接调 ``POST /generate`` 并保存；
- AI 对话走 Agent 工具，确认后由 ``plans.service.save_plan`` 落库。

本模块不调用 LLM，生成结果完全由 ``plans.generator`` 的动作库规则决定。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field

from agent.plans.catalog import muscle_catalog_payload
from agent.plans.generator import PlanValidationError, build_plan
from agent.plans.service import delete_plan, get_plan, list_plans, save_plan, update_plan_swaps

router = APIRouter()


class PlanGenerateRequest(BaseModel):
    """人体图一键生成计划的请求。"""

    user_id: str = Field(description="用户标识（UUID 或用户名）", min_length=1)
    experience: str = Field(description="beginner/experienced，或新手/老手")
    split: str = Field(description="three_day/five_day，或三分化/五分化")
    focus_muscles: list[str] = Field(default_factory=list, max_length=10, description="重点肌群")
    preferred_exercises: list[str] = Field(default_factory=list, max_length=30, description="用户点名的动作")
    day_focus: list[str] | None = Field(default=None, max_length=5, description="每个训练日的部位，可为空走默认模板")
    goal: str = Field(default="增肌", description="增肌/力量/减脂/塑形")
    plan_name: str | None = Field(default=None, max_length=100, description="可选自定义计划名")


class PlanSwapItem(BaseModel):
    """一次换动作。"""

    slot_id: str = Field(description="计划里的动作位置，如 d1e1", min_length=1)
    exercise_name: str = Field(description="替换后的动作名", min_length=1)


class PlanSwapRequest(BaseModel):
    """PATCH /plan/{plan_id} 的请求。"""

    user_id: str = Field(description="用户标识（UUID 或用户名）", min_length=1)
    swaps: list[PlanSwapItem] = Field(default_factory=list, max_length=30)


class PlanResponse(BaseModel):
    """单个计划响应。"""

    plan: dict


class PlanListResponse(BaseModel):
    """计划摘要列表响应。"""

    plans: list[dict] = Field(default_factory=list)


@router.get("/muscles", tags=["plan"], summary="列出 10 个训练肌群的新手/老手动作")
async def get_muscles() -> dict:
    """返回人体图右侧动作面板所需的数据。

    动作来自静态动作库，不查 MySQL；前端按 ``id`` 把肌群和 3D 模型匹配。
    """
    return muscle_catalog_payload()


@router.post("/generate", tags=["plan"], summary="按经验/分化/重点肌群生成并保存计划")
async def generate_plan(request: PlanGenerateRequest) -> PlanResponse:
    """人体图入口：生成计划后直接保存。"""
    try:
        plan = build_plan(
            experience=request.experience,
            split=request.split,
            day_focus=request.day_focus,
            focus_muscles=request.focus_muscles,
            preferred_exercises=request.preferred_exercises,
            goal=request.goal,
            plan_name=request.plan_name,
        )
        saved = await save_plan(request.user_id, plan, source="anatomy")
    except PlanValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    logger.info(f"Plan generated: user={request.user_id}, plan_id={saved.get('plan_id')}")
    return PlanResponse(plan=saved)


@router.get("/list", tags=["plan"], summary="我的计划列表")
async def get_plans(
    user_id: str = Query(description="用户标识"),
    limit: int = Query(default=20, ge=1, le=50, description="最多返回条数"),
) -> PlanListResponse:
    """返回当前用户的计划摘要，最新的在前。"""
    return PlanListResponse(plans=await list_plans(user_id, limit))


@router.get("/{plan_id}", tags=["plan"], summary="计划详情")
async def get_plan_detail(plan_id: str, user_id: str = Query(description="用户标识")) -> PlanResponse:
    """按 id 取计划；不属于该用户时统一 404，避免泄露存在性。"""
    plan = await get_plan(user_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有找到这个训练计划。")
    return PlanResponse(plan=plan)


@router.patch("/{plan_id}", tags=["plan"], summary="更换计划里的动作")
async def swap_plan_exercises(plan_id: str, request: PlanSwapRequest) -> PlanResponse:
    """替换动作并保存；校验同肌群、水平兼容、最终不重名。"""
    try:
        updated = await update_plan_swaps(
            request.user_id,
            plan_id,
            [item.model_dump() for item in request.swaps],
        )
    except PlanValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有找到这个训练计划。")
    return PlanResponse(plan=updated)


@router.delete("/{plan_id}", tags=["plan"], summary="删除计划")
async def remove_plan(plan_id: str, user_id: str = Query(description="用户标识")) -> dict:
    """删除计划；不存在/不属于该用户返回 404。"""
    removed = await delete_plan(user_id, plan_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有找到这个训练计划。")
    return {"status": "ok"}
