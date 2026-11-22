---
name: cs2-daily
description: 拉取今日 CS2 战绩并生成日报（同步对局 → demo 分析 → 复盘要点摘要），供用户一句话触发。
---

# /cs2-daily

按顺序执行（CS2HQ 后端需在 8101 运行；MindVault 需在 8001/8300 运行）：

1. **同步对局**：
   ```bash
   TID=$(curl -s -X POST http://127.0.0.1:8101/api/tasks -H "Content-Type: application/json" -d '{"type":"wanmei_sync"}' | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
   curl -s -X POST http://127.0.0.1:8101/api/tasks/$TID/run
   ```
   若状态为 NEED_AUTH：提示用户去面板设置页重新短信登录，终止。

2. **分析最近对局**：`GET /api/matches` 取最近 3 场 `demo_status` 为 `none` 或 `pending_demo` 的对局，逐个：
   ```bash
   curl -s -X POST http://127.0.0.1:8101/api/tasks -H "Content-Type: application/json" -d '{"type":"demo_analyze","payload":{"match_id":"<matchId>"}}'
   curl -s -X POST http://127.0.0.1:8101/api/tasks/<id>/run
   ```
   failed 且 error 含"客户端"：告知用户"在完美客户端对局回放里点开该场 demo 即自动下载，之后重跑 /cs2-daily"。

3. **汇总输出**：`GET /api/matches` 与 `GET /api/matches/<id>` 的 `report` 摘要，向用户输出：
   - 今日战绩行（地图/比分/胜负/rating）
   - 每场复盘的「今日唯一重点」与失误 top3 标题
   - 提醒：完整复盘已推送 MindVault「CS2复盘」主题。

## 禁区
- 完美平台 401/403 时**不要重试**，直接提示重新登录。
- B站/道具相关请求一律不在本 skill 内触发（用 /cs2-learn）。
