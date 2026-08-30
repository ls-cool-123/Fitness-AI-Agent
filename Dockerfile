# ============================================================
# 后端 Agent 镜像 — FastAPI + LangGraph 服务
# ============================================================

# 基础镜像：uv 官方镜像，预装 Python 3.13 + uv 包管理器
# bookworm-slim 是 Debian 精简版，减小最终镜像体积
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# ----- 构建环境变量 -----

# 安装时编译 .pyc 字节码，加快容器启动后模块加载速度
ENV UV_COMPILE_BYTECODE=1

# 使用硬拷贝而非符号链接安装包（Docker 层缓存要求，符号链接在跨层时失效）
ENV UV_LINK_MODE=copy

# 使用官方 PyPI 源。清华镜像源（pypi.tuna.tsinghua.edu.cn）自 2026-08-29 起
# SSL 握手失败（宿主机与容器内均复现），临时切回官方源。
# 清华源恢复后如需加速可改回 https://pypi.tuna.tsinghua.edu.cn/simple
ENV UV_INDEX_URL=https://pypi.org/simple

# 下载超时时间 300 秒，避免大包或网络波动导致安装失败
ENV UV_HTTP_TIMEOUT=300

# ----- 第一层：安装第三方依赖（利用 Docker 层缓存） -----
# 先只复制依赖声明文件，不复制源码
# 这样只要依赖没变，这层就能命中缓存，跳过重复安装
#
# 注意：不复制 uv.lock —— uv sync 有 lock 文件时会忽略 UV_INDEX_URL，
# 直接用 lock 文件里写死的 files.pythonhosted.org 下载 URL。
# 没有 lock 文件时 uv 从 UV_INDEX_URL（见上，当前为官方源）解析和下载。
COPY ./pyproject.toml ./pyproject.toml
COPY ./README.md ./README.md

# --no-install-project: 先不装项目本身，等源码复制进来后再装
RUN uv sync --no-install-project

# ----- 第二层：安装项目源码 -----
# 依赖已装完，现在复制源代码
# 之后改代码只会让这一层失效重建，上面的依赖层依然命中缓存
COPY ./src /src

# 再次 sync，这次会安装 src/ 下的项目包
RUN uv sync

# ----- 容器启动命令 -----
# 用 uv run 启动 uvicorn，监听所有网络接口的 8001 端口
# 注意：docker-compose.yml 会用 --reload 覆盖此命令，实现开发热重载
CMD ["uv", "run", "uvicorn", "src.agent.main:app", "--host", "0.0.0.0", "--port", "8001"]
