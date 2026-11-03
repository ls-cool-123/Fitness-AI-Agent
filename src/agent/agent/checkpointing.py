"""会话状态持久化（Checkpointer）初始化。

Checkpointer 决定 LangGraph 把 "当前对话走到哪、有哪些待恢复的任务" 存在哪里。
本项目支持三种后端，由 ``CHECKPOINT_BACKEND`` 切换：

============  ==========================================================
memory        进程内字典。重启即丢，仅用于单测与无外部依赖的本地调试。
sqlite        单文件持久化。不需要额外服务，用来本地复现"重启续聊"。
postgres      生产形态。docker-compose 的 postgres 服务提供，支持多进程
              共享（uvicorn 多 worker / 多副本）与崩溃恢复。
============  ==========================================================

为什么不用 MemorySaver：它把状态放在进程内存里，服务一重启，用户正在进行的
对话、以及被 ``interrupt()`` 挂起等待确认的训练记录会一起消失——HITL 也就
变成了假的（暂停后重启用用户再点确认，后端根本找不到这个暂停点）。
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from loguru import logger

from agent.utils.config import Config


class CheckpointerHandle:
    """checkpointer 及其底层资源的生命周期句柄。

    ``saver`` 传给 ``create_agent(checkpointer=...)``；``aclose()`` 在应用
    关闭时释放数据库连接或关闭 sqlite 文件。
    """

    def __init__(
        self,
        saver: Any,
        backend: str,
        stack: AsyncExitStack | None = None,
    ) -> None:
        self.saver = saver
        self.backend = backend
        self._stack = stack

    async def aclose(self) -> None:
        """释放底层连接。memory 后端无需清理。"""
        if self._stack is not None:
            await self._stack.aclose()
            logger.info(f"Checkpointer ({self.backend}) closed.")


async def _init_postgres(cfg: Config, stack: AsyncExitStack) -> Any:
    """建立 Postgres 连接并建表（setup 幂等，可重复执行）。"""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: PLC0415

    saver = await stack.enter_async_context(
        AsyncPostgresSaver.from_conn_string(cfg.postgres_dsn)
    )
    # 首次启动时创建 checkpoint 相关的表；已存在则为 no-op
    await saver.setup()
    return saver


async def _init_sqlite(cfg: Config, stack: AsyncExitStack) -> Any:
    """打开 sqlite 文件（不存在则创建）。"""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: PLC0415

    path = Path(cfg.sqlite_checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    saver = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(str(path)))
    # 不同版本的 sqlite saver 建表时机不同，显式调用一次更稳妥
    setup = getattr(saver, "setup", None)
    if setup is not None:
        await setup()
    return saver


async def init_checkpointer(cfg: Config | None = None) -> CheckpointerHandle:
    """按配置初始化 checkpointer。

    后端初始化失败时（例如 compose 里没起 postgres），若
    ``checkpoint_fallback_to_memory`` 为真则降级到内存实现并告警——
    降级的代价是丢失持久化能力，但服务仍然可用。

    Args:
        cfg: 应用配置，为 None 时使用全局 Config 单例。

    Returns:
        CheckpointerHandle: 持有 saver 与清理逻辑。
    """
    cfg = cfg or Config()
    backend = cfg.checkpoint_backend

    if backend == "memory":
        logger.info("Checkpointer backend: memory (非持久化)")
        return CheckpointerHandle(InMemorySaver(), backend)

    stack = AsyncExitStack()
    try:
        if backend == "postgres":
            saver = await _init_postgres(cfg, stack)
        else:  # sqlite
            saver = await _init_sqlite(cfg, stack)
    except Exception as exc:
        await stack.aclose()
        if not cfg.checkpoint_fallback_to_memory:
            raise
        logger.warning(
            f"Checkpointer backend '{backend}' 初始化失败，降级为 memory：{exc}"
        )
        return CheckpointerHandle(InMemorySaver(), "memory")

    logger.info(f"Checkpointer backend: {backend}")
    return CheckpointerHandle(saver, backend, stack)
