---
name: cs2-review
description: 深度复盘指定对局（demo 四维解析 + AI 复盘 + 推送 MindVault），参数为 matchId 或"最近一场"。
---

# /cs2-review [matchId]

1. 无参数时取 `GET /api/matches` 最近一场；有参数则按 matchId 定位。
2. 创建并执行 `demo_analyze` 任务（payload.match_id）。
3. `GET /api/matches/<id>` 读 `analysis`（四维 JSON），把**对枪矩阵热力图数据、死亡还原要点、今日唯一重点**整理成表格输出给用户。
4. 复盘笔记 uuid 在任务 result 中；告诉用户 MindVault 可搜的标题。

任务 failed 时按 error 分类提示：缺 demo → 引导客户端点开；NEED_AUTH → 设置页重登；AI 相关 → 检查设置页 ai.api_key。
