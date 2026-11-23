"""PROMPT_DIR 解析回归：容器内曾算成 /backend/app/ai_skills 导致 load_prompt 返回空。

场景（deepen-task 探针实证的生产隐患）：
- Given ai_client.py 位于 app/services/ 下
- When  计算 PROMPT_DIR
- Then  必须指向模块同级的 app/ai_skills（相对 __file__，不依赖 cwd / 仓库根假设）
- And   load_prompt("bili_learn") 非空（容器内曾为 "" → 全部走 fallback prompt）
"""
from pathlib import Path

from app.services.ai_client import PROMPT_DIR, load_prompt


class TestPromptDirResolution:
    def test_prompt_dir_is_module_relative(self):
        """PROMPT_DIR 必须由 __file__ 推导：services/ 的上一级 / ai_skills。"""
        expected = Path(__file__).resolve().parents[1] / "app" / "ai_skills"
        assert PROMPT_DIR == expected, (
            f"PROMPT_DIR={PROMPT_DIR} ≠ {expected}；"
            "曾用仓库根拼接（parents[2]/backend/...），容器内 WORKDIR=/app 时算成 / → load_prompt 返回空"
        )

    def test_load_prompt_non_empty_in_any_layout(self):
        """无论从哪个 cwd 启动，prompt 都能加载（容器 uvicorn 从 /app 启动）。"""
        import os

        old = os.getcwd()
        try:
            os.chdir("/")  # 模拟容器 WORKDIR
            prompt = load_prompt("bili_learn")
        finally:
            os.chdir(old)
        assert prompt and len(prompt) > 500, "prompt 加载为空或过短 → AI 走 fallback，结构化字段丢失"
