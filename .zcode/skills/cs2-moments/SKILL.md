---
name: cs2-moments
description: 同步完美时刻：扫描导出目录 → 压缩 → 推送 MindVault 可播放。无参数执行同步。
---

# /cs2-moments

1. 确认设置：`GET http://127.0.0.1:8101/api/settings` 检查 `moments.dir`（未配置则让用户在面板设置页填写完美客户端导出时刻的文件夹路径）。
2. POST /api/tasks `{"type":"moments_sync"}` → run。
3. 结果呈现：pushed（新推送数）/ skipped（已推过）/ failed；failed>0 时列出对应文件名与原因（超 20MB 且压缩失败等）。
4. 提醒：时刻视频已可在 MindVault 公网「CS2完美时刻」主题播放。

## 禁区
- 不要尝试从 wmpvp 接口抓时刻（端点未公开，抓包方案留待后续）；只用用户导出的本地文件。
- 压缩失败不要无限重试（单文件一次，失败即报）。
