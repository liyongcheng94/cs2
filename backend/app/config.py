"""配置：数据目录按调用时读取环境变量（测试可隔离），路径约定集中于此。"""
from __future__ import annotations

import os
from pathlib import Path

APP_VERSION = "0.1.0"


def get_project_root() -> Path:
    """backend/app/config.py → 仓库根 D:\\project\\cs2。"""
    return Path(__file__).resolve().parents[2]


def get_data_dir() -> Path:
    root = Path(os.environ.get("CS2HQ_DATA_DIR") or get_project_root() / "data")
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_log_dir() -> Path:
    d = get_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
