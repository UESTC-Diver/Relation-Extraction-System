# -*- coding: utf-8 -*-
"""项目一键启动入口。

用法（在 backend 目录下）：
    python main.py              # 直接启动，访问 http://127.0.0.1:8000
    python main.py --reload     # 开发模式（代码热更新）
    python main.py --port 9000  # 自定义端口

本入口会自动复用 app/main.py 中定义的 FastAPI 应用：
安装依赖（pip install -r requirements.txt）后即可单命令启动，
后端检测到 frontend/dist 时会同时托管前端页面。
"""

from __future__ import annotations

import argparse
import os
import sys

# 保证以 `python main.py` 直接运行时，backend 目录在 sys.path 中，
# 这样 uvicorn 才能以 "app.main:app" 导入应用包。
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import uvicorn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="中文关系抽取系统 - 启动器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码变更自动重启")
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[BACKEND_DIR] if args.reload else None,
    )


if __name__ == "__main__":
    main()
