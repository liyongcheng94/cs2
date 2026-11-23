"""OCR 服务：RapidOCR 识别截图文本（AI 教练图片对话的"眼睛"）。

设计（2026-11-23 用户选型：DeepSeek 无 vision → OCR 文字间接注入）：
- 识别结果按阅读序（y 中心聚类分行，行内按 x 排序）拼接
- OCR 失败/无文本 → 返回 ""（不阻断上传，AI 端只少一段上下文）
- lazy import：rapidocr 较重，首次调用才加载
"""
from __future__ import annotations

from pathlib import Path


def ocr_image(path: str | Path) -> str:
    """识别单张图片，返回按阅读序拼接的文本；失败返回空串。"""
    try:
        from rapidocr_onnxruntime import RapidOCR

        ocr = RapidOCR()
        result, _ = ocr(str(path))
        if not result:
            return ""
        rows: list[tuple[float, float, str]] = []
        for box, text, _score in result:
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            rows.append((sum(ys) / 4, sum(xs) / 4, text))
        # 阅读序：y 聚类成行（40px 容差），行内按 x
        rows.sort(key=lambda r: r[0])
        lines: list[str] = []
        cur: list[tuple[float, str]] = []
        last_y: float | None = None
        for y, x, t in rows:
            if last_y is None or y - last_y <= 40:
                cur.append((x, t))
            else:
                lines.append(" ".join(t for _, t in sorted(cur)))
                cur = [(x, t)]
            last_y = y
        if cur:
            lines.append(" ".join(t for _, t in sorted(cur)))
        return "\n".join(lines)
    except Exception:
        return ""
