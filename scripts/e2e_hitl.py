"""端到端验证：Postgres checkpointer + HITL 跨进程恢复。

这个脚本回答一个问题：训练记录写到一半把服务杀掉，重启后还能不能接着确认？

流程（每个阶段是一个独立进程，忠实模拟"重启"）：

1. pause   —— 起服务，发一条"记录训练"的请求。Agent 调 add_workout_tool 时
              interrupt 暂停，响应里带确认载荷。进程随后退出。
2. confirm —— 起一个新的服务进程（新的 checkpointer / 新的事件循环），直接调
              /chat/confirm。能 resume 说明中断状态真的落在 Postgres 里。
3. 校验     —— 训练记录确实写进 MySQL；重复确认返回 409。

为什么分进程：SQLAlchemy 的异步引擎绑定在创建它的事件循环上，同一个进程里
连开两个 TestClient 会触发 "attached to a different loop"。真实重启本就是换
进程，这样测也更接近线上。

用法：
    uv run python scripts/e2e_hitl.py

前置：docker compose up -d qdrant mysql postgres
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time

# Windows 默认的 ProactorEventLoop 不支持 psycopg 的异步连接，必须在创建任何
# 事件循环之前切到 SelectorEventLoop（Linux 容器内无此问题）。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 必须在 import agent.* 之前设置：配置在模块导入时就被读取了
os.environ.setdefault("CHECKPOINT_BACKEND", "postgres")
os.environ.setdefault(
    "POSTGRES_DSN", "postgresql://fitness:fitness@localhost:5433/fitness_agent"
)
os.environ.setdefault("WORKOUT_CONFIRM_ENABLED", "true")

# 这个脚本只验证 checkpointer 与 HITL，不需要链路追踪；
# 关掉 Phoenix 上报可以避免本地没起 phoenix 容器时刷屏的 DNS 报错。
from unittest.mock import patch  # noqa: E402

for _p in (
    patch("phoenix.otel.register", return_value=None),
    patch(
        "openinference.instrumentation.langchain.LangChainInstrumentor.instrument",
        return_value=None,
    ),
):
    _p.start()

from fastapi.testclient import TestClient  # noqa: E402

from agent.main import app  # noqa: E402


def _fail(message: str) -> None:
    print(f"❌ {message}")
    raise SystemExit(1)


def phase_pause(user_id: str, conversation_id: str) -> None:
    """阶段 1：发起记录请求，验证 Agent 在写库前暂停。"""
    payload = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "messages": [
            {"role": "user", "content": "帮我记录今天的训练：深蹲 80kg 5组5次"}
        ],
    }

    with TestClient(app) as client:
        if client.get("/").status_code != 200:
            _fail("健康检查失败")

        response = client.post("/chat", json=payload)
        if response.status_code != 200:
            _fail(f"/chat 返回 {response.status_code}: {response.text[:400]}")

        body = response.json()
        if not body.get("interrupt"):
            _fail(f"预期在写库前暂停，但响应里没有 interrupt：{json.dumps(body, ensure_ascii=False)[:400]}")

        preview = body["interrupt"]["value"].get("preview") or []
        if not preview:
            _fail("interrupt 载荷里没有 preview，前端无法展示确认卡片")

        item = preview[0]
        print(f"   ✅ 已暂停等待确认：{json.dumps(preview, ensure_ascii=False)}")
        if item.get("reps_per_set") != 5 or item.get("sets") != 5:
            _fail(
                f"预览的动作次数不对（应为 5 组 × 5 次）：sets={item.get('sets')}, "
                f"reps={item.get('reps')}, reps_per_set={item.get('reps_per_set')}"
            )

    print("   ⏹  进程退出（模拟服务被重启）")


def phase_confirm(user_id: str, conversation_id: str) -> None:
    """阶段 2：新进程里确认上一次挂起的写入，并校验落库。"""
    with TestClient(app) as client:
        confirm = client.post(
            "/chat/confirm",
            json={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "approved": True,
                "edits": [
                    {"name": "深蹲", "sets": 5, "reps": 25, "reps_per_set": 5, "weight_kg": 80}
                ],
            },
        )
        if confirm.status_code != 200:
            _fail(f"重启后无法恢复中断（{confirm.status_code}）：{confirm.text[:400]}")
        print(f"   ✅ 跨进程恢复成功，回答：{confirm.json().get('answer', '')[:60]}")

        dup = client.post(
            "/chat/confirm",
            json={"user_id": user_id, "conversation_id": conversation_id, "approved": True},
        )
        if dup.status_code != 409:
            _fail(f"重复确认应返回 409，实际 {dup.status_code}")
        print("   ✅ 重复确认被拒绝（409），不会重复写库")

        history = client.get(
            "/workout/history", params={"user_id": user_id, "days_back": 7}
        )
        sessions = (history.json() if history.status_code == 200 else {}).get("sessions") or []
        if not sessions:
            _fail("训练记录没有落库")

        exercises = sessions[0].get("items") or []
        print(f"   ✅ 已落库：{json.dumps(exercises, ensure_ascii=False)[:200]}")
        if not any("深蹲" in str(item.get("exercise") or item.get("name")) for item in exercises):
            _fail(f"落库的动作不是深蹲：{exercises}")

        # 次数语义也要对：5 组 × 5 次应当存成 total=25
        first = exercises[0]
        if first.get("sets") != 5 or first.get("reps") != 25:
            _fail(f"落库的组数/总次数不对：sets={first.get('sets')}, reps={first.get('reps')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["all", "pause", "confirm"], default="all")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--conversation-id", default=None)
    args = parser.parse_args()

    stamp = int(time.time())
    user_id = args.user_id or f"e2e-hitl-{stamp}"
    conversation_id = args.conversation_id or f"conv-{stamp}"

    if args.phase == "pause":
        print("\n[1/3] 发起记录训练请求 ...")
        phase_pause(user_id, conversation_id)
        return

    if args.phase == "confirm":
        print("\n[2/3] 新进程中确认挂起的写入 ...")
        phase_confirm(user_id, conversation_id)
        print("\n[3/3] 校验完成")
        return

    # 主进程：用子进程串起两个阶段，确保是真正的"换进程"
    script = os.path.abspath(__file__)
    common = ["--user-id", user_id, "--conversation-id", conversation_id]

    print("\n[1/3] 发起记录训练请求 ...")
    pause = subprocess.run([sys.executable, script, "--phase", "pause", *common], check=False)
    if pause.returncode != 0:
        _fail("暂停阶段失败")

    print("\n[2/3] 重启进程并确认挂起的写入 ...")
    confirm = subprocess.run([sys.executable, script, "--phase", "confirm", *common], check=False)
    if confirm.returncode != 0:
        _fail("恢复阶段失败")

    print("\n[3/3] 完成")
    print("\n✅ 全部通过：中断状态跨进程存活，确认后正确落库，重复确认被拦截。")


if __name__ == "__main__":
    main()
