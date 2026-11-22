---
name: cs2-learn
description: 学道具：B站检索/手动BV → 字幕 → AI 总结+道具卡 → 推送 MindVault 道具库。参数为 BV 号或关键词（如 /cs2-learn CS2 A大 烟雾）。
---

# /cs2-learn <BV号|关键词>

1. 组 payload：参数以 BV 开头 → `{"type":"bili_learn","payload":{"bvid":"<BV>"}}`；否则 `{"keyword":"<参数>"}`。
2. POST http://127.0.0.1:8100/api/tasks → POST /api/tasks/{id}/run。
3. 结果分类呈现：
   - status=NEED_AUTH / error 含 SESSDATA → 提示设置页粘贴 B站 SESSDATA。
   - error 含风控（-412/-352）→ 告知"B站风控暂停 ≥1h，可稍后重试或直接给 BV 号"。
   - results[].status=no_subtitle → 告知该视频无 CC 字幕（可换一个视频）。
   - results[].cards 数 → 列出每张道具卡（地图/点位/投掷物/时机），提醒已入 MindVault「CS2道具库」主题。
4. 失败 error 含 AI → 检查设置页 ai.api_key。

## 禁区
- 不要绕过平台 API 直接爬网页；风控触发后不要立即重试。
- 单次最多 5 条视频（任务内已限）。
