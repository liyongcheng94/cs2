# CS2HQ 架构与计划（v5 终版，2026-11-22 评审结案）

> 本文件是进度对照文档：每阶段完成后在对应小节打勾并附验收证据。

## Context（为什么做）

用户是完美平台 CS2 玩家（高敏 eDPI≈1000+ / OMR248 鼠标 / 主玩 Dust2 / 狙击A级·残局B级强项，突破·补枪·道具 C级短板——来自 DeepSeek 对话历史还原）。目前的提升闭环全靠手动。目标：**自动化闭环——战绩自动拉、demo 自动析、失误自动总结、教学视频自动学、道具自动建卡，全部沉淀到 MindVault 公网可查**，Web 面板 + ZCode skills 双入口。

## 已确认决策

1. Web 面板首版；2. 四能力全做；3. 完美平台手动 token 主 + 浏览器自动化兜底；4. 道具卡自动抽取；5. 独立项目 + MCP 推送 MindVault；6. MindVault 基座栈（FastAPI+SQLModel+SQLite / React+antd+Vite / TDD+BDD）；7. demo 四维分析首版全做；8. 全自动入库；9. 时刻视频压缩≤20MB + MindVault 加 `/api/capture/videos`；10. AI 复用 MindVault 模式（DeepSeek/GLM/Ollama 可切）；11. 首版带 ZCode skills（极简版随阶段 2）；12. 项目名 CS2HQ；13. B站 ASR 首版砍掉（无字幕标 `no_subtitle` 跳过）。

## 关键事实（调研结论）

- **MindVault 写入通道**：MCP `POST /api/mcp` 只有 create 无 update（工具 search/list_items/get_item/create_note/ask/append_daily，`api/mcp.py:39-78`）；REST 有 `PUT /api/items/{uuid}`；auth 经 `/api/auth/login` 换 Bearer；公网 Cloudflare Quick Tunnel（`--protocol http2`）；blobs `GET /api/blobs/{path}`，上传限 20MB（`media_service.py:15`）。
- **完美平台**：token 取自 partner.wmpvp.com cookie（与 mySteamId 1:1，登录轮换）；`POST api.wmpvp.com/api/csgo/home/match/list` + `/api/csgo/home/pvp/detailStats`（头：token + appversion:3.5.4.172 + platform:android）；demo 签名 URL 会过期；完美时刻 `acty/community/moments/getPersonalMoments` 返回 mp4 直链。**禁止 PWHook 注入（封号风险）**。
- **B 站**：检索需 WBI 签名 + buvid3 引导；字幕必须走 `/x/player/wbi/v2`（需 SESSDATA）；风控码 -412/-352/10031/12051/12015；个人低频抓取、限速 1s。
- **demo 解析候选**：demoparser2（OOP）vs awpy（Polars 向量化）——spike 实测定选，必测 30min demo 耗时/峰值内存。

## 实施计划（阶段闸门）

### [x] 阶段 0：基座 + MindVault 视频端点 + Mock 全链路（2026-11-22 完成）
- backend/（FastAPI+SQLModel+SQLite）+ frontend/（React+antd+Vite）+ AGENTS.md + git 分支 feature/phase-0-base + loguru + 依赖 `==` 锁版。
- 表：matches / match_stats / demo_analyses(JSON 四维) / clips / bili_videos / grenade_cards / reports / player_profile / settings / tasks(含 priority)。数据访问收敛 services 层；迁 PostgreSQL 预案见 AGENTS.md。
- 凭证 Fernet 加密存 settings；secret.key 环境变量 + .gitignore。
- JSON schema 四维基线指标全字段预留（距离分桶胜率/劣势枪位死亡/有效购买比例/首杀转化率/致盲时长中位数/道具浪费率/先手vs后手胜率/镜像对枪胜率）。
- MindVault 加 `POST /api/capture/videos`（{source_hash}_{preset_hash} 寻址、.tmp→os.rename 原子写、已存在且大小一致直接返回；TDD 流程）。
- Mock 全链路：`POST /api/test/mock-flow` 假数据跑通 后端→面板→MCP→MindVault。
- 前端 React Query 轮询 `GET /api/tasks`（5s）。
- 闸门：pytest 绿 + tsc 过 + MindVault 新端点绿 + verify.bat 内 mock-flow 走通。
- **验收证据（2026-11-22）**：CS2HQ 后端 21 用例全绿，覆盖率 94%（门禁基线 89% 写入 AGENTS.md）；前端 tsc PASS + vite 5174 冒烟 200（/api 代理连通）；MindVault 新端点 7 用例绿，全量 1102 用例 93.18%≥92% 门禁不降；Mock 全链路真库验收：CS2HQ(Fernet 加密密码)→MindVault 登录换令牌→MCP create_note 返回 uuid=111491da-a344-4170-9ee8-70dd4ce1d1aa，`GET /api/search?q=MOCK` 命中，「CS2复盘」主题自动创建（验收实例为临时数据目录 `data/mv-acceptance`，未触碰真实知识库）。

### [x] 阶段 1：完美平台数据链路（2026-11-22 完成）
- 2026-11-22：**登录方案修正**——partner.wmpvp.com 为合作方入口（state=appAdmin），普通玩家报"没有授权"；改从 partner 门户 JS 逆向出完整短信登录链路：`passport.pwesports.cn` 的 `initcaptcha → WanmeiCaptcha 滑块（appId 20041，用户自过）→ GET /securitycode?mobilePhone&secCode&capTicket&reason=1 → POST /account/login {appId:10}` → token+steamId。
- **真实响应结构（2026-11 实测，社区 2023 文档已过时）**：信封为 `{statusCode, errorMessage, data:{matchList:[...]}}`；行内 winTeam/team 为 1/2 整数（胜负=winTeam==team 精确判定）、mapName 中文（荒漠迷城）、startTime 本地时间字符串、mvp/pvpMvp 布尔、we=WE 评分。
- `services/wanmei.py`（PassportClient 三步 + WanmeiAPI match_list/detailStats，401/403→WanmeiAuthError 熔断）；`services/wanmei_sync.py`（wanmei_sync 任务：3 页/次、页间 2s、幂等 UPSERT）；API `/api/wanmei/{captcha-init,send-code,sms-login,status}`；token Fernet 加密落库。
- 32 后端用例全绿（含 NEED_AUTH 熔断、幂等重同步）；前端 WanmeiLogin 对话框 + 对局页同步按钮，tsc PASS。
- **闸门证据（2026-11-22）**：用户面板真实短信登录成功 → 首次同步 3 页 **60 场真实对局入库**，二次同步 inserted=0/updated=60（幂等不重复）；MOCK 假数据已清理；NEED_AUTH 熔断由单元测试覆盖（真实 token 反失效演练需再耗一次短信，未执行破坏性验证）。

### [x] 阶段 2：demo 解析 + AI 复盘（2.5 天，核心）——2026-11-23 勾选修正：spike 已落 docs/spike-demo-parsers.md（awpy 3.3.0 选型，2.4s/18MB vs demoparser2 5.0s/50MB），四维/复盘/推送链路已全通（此前文档勾选滞后于实际）
- spike：demoparser2 vs awpy 双基准（API 体验 + 30min demo 耗时/峰值内存）；按需提取（对枪 player_death、道具 grenade_throw+player_blind、劣势枪位死亡前 1s 坐标+Yaw/Pitch）；仍慢按回合分块。结论落 docs/。
- CPU 任务隔离：`asyncio.to_thread()` + Semaphore(1) 串行防 OOM。
- `services/demo_dl.py`：签名 URL 下载；失败 5s 重试 1 次 → pending_demo 下轮凌晨批量；解析产出 JSON 后立即删 raw demo。
- `services/demo_analysis.py`：四维 JSON 按 schema。
- `services/report.py`：Pydantic ReviewOutput 校验（失败重试 1 次 → 纯文本降级）；防幻觉证据链（失误必须引用 JSON 字段，无支撑宁可"无明显失误"）；今日唯一重点双轨制（Rule-based 硬红线优先）；关闭思考模式。
- 推送幂等：source_hash = hash(matchId + prompt_version)；前置查重 → 已存在 REST PUT 更新，新报告 MCP create_note。
- 极简 /cs2-daily skill 上线。
- 闸门：真实 demo → 四维 JSON → 面板 → 复盘过校验 → MindVault 可搜；坏输出验证降级；spike 数据落 docs/。

### [~] 阶段 3：B 站视频管线 + 道具卡（链路全通，总结/道具卡待 AI Key）
- 2026-11-22 夜间完成：`services/bili.py`（自研 WBI 签名检索，MindVault 同款算法；字幕走 bilibili-api 17.4.2 `get_subtitle(cid=pages[0])`，SESSDATA 登录态）；`services/bili_learn.py`（任务 bili_learn：BV/关键词 → 字幕 → AI 总结+道具卡 → 推送 CS2视频总结 主题）。
- **真实冒烟**：检索"CS2 烟雾弹 教学"命中 20 条；BV1Ub421v7ug（道具手教学）ai-zh 字幕 7219 字；端到端：字幕→降级原文→推送 MindVault（uuid 584cf046，可搜）；无字幕视频正确标 no_subtitle。
- 风控软着陆就位（BiliRiskError → -412/-352 → 任务层暂停 ≥1h）。
- ✅ 2026-11-23 闸门完成：AI 桥（provider=mindvault 借公网 DeepSeek）真 AI 总结 + **7 张道具卡**入库 CS2道具库（Mirage B区/B2楼闪光、B小道/警察/VIP烟）；公网搜索 "CS2" 命中 12 条。修复：编排器/bili_learn 此前硬编码 ai=None 或按 api_key 判空（MindVault 桥无需 key）导致 AI 从未被调用。

### [~] 阶段 4：完美时刻（管线就绪，真实数据待用户导出）
- 2026-11-22 夜间完成：getPersonalMoments 端点实测 404（未公开，抓包方案留待后续不阻塞）——改用**与 demo 同构的客户端协作方案**：用户导出时刻 mp4 到 moments.dir（设置页配置）→ `services/moments.py` 扫描 → ≤20MB 直推 / 超限 ffmpeg（imageio-ffmpeg 静态二进制，-preset veryfast 720p/CRF28）→ MindVault `/api/capture/videos` → Clip 行幂等。
- 任务 moments_sync；ffmpeg 真实压缩链路已测试（test_compress_real_ffmpeg 用 ffmpeg 自生成源验证）。
- 待真实数据：用户导出 ≥1 条时刻 → 推送 → 公网 MindVault 可播放。

### [~] 阶段 5：整合收口（2026-11-22 夜间大部分完成）
- 已完成：scheduler 错峰接入 lifespan（每2h同步/凌晨03:30 demo批量，测试环境 CS2HQ_SCHEDULER=0 禁用）；skills /cs2-daily /cs2-review 就绪；设置页补 AI Key 与时刻目录字段；覆盖率门禁修订 87%（68 项依赖锁版）；verify.bat 同步。
- 待办（晨间）：ECharts 对枪热力图/死亡散点（analysis JSON 已就绪）；周报周日推送；cf-tunnel 公网开启（URL 随机，晨间启动即可）；视频总结/道具库前端页面；完整版 /cs2-learn /cs2-moments skills。
- 已知待修：平局场次胜负判定（等下批真实数据观察 winTeam 口径）。

## 二期（2026-11-23 全部落地）

- ✅ 平局口径：实测 winTeam=-1 → API 派生 draw 字段，UI 显示"平"（11 场历史平局全部正确标注）
- ✅ 死亡散点雷达底图：awpy-data 官方雷达 PNG×7（1024²）+ 权威坐标映射（pos_x/pos_y/scale），frontend/public/radar/；matches API 派生 map_en（中文→ID 映射表）；散点带击杀方向连线
- ✅ 对话流式：DeepSeek stream:true → SSE `/api/chat/stream`（delta/done 事件）→ 前端逐字渲染；mindvault 桥自动回退单段；实测逐字推送且内容基于画像口径
- ✅ 周报 AI 周评：聚合数据 → AI 段落（失败跳过不降级）
- ⏸ 时刻端点抓包：需用户抓包配合，挂起

## 三期：洞察增强 insights-v1（2026-11-23，分支 feature/insights-v1，worktree D:\project\cs2-improvements）

> 调研（awpy/cs-demo-manager/cs2-highlights-maker 等开源对标）后落地：解析层零换库（awpy 3.3.0 数据集吃满），上层功能四方向补齐。SCHEMA 1.0→1.1 向后兼容（旧字段保留，新增字段可 null）。

### ✅ P0：bug 修复 + 道具分析 v2（补短板：强狙击弱道具）
- ✅ weekly.py `import json` 缺失 → AI 周评 NameError 被 except 吞掉静默失效（标记断言测试防回归）
- ✅ bili_learn `_ai_summarize` AI 返回非 JSON → AttributeError 崩任务（降级为原文标注 + 空卡）
- ✅ 炸弹/世界击杀（planted_c4）无攻击者坐标 → `_xyz_dist` TypeError 崩解析（真实 demo 3/114 行实测触发；死亡不入距离桶、对枪矩阵跳过）
- ✅ 闪光有效性敌友拆分（awpy blinds 数据集替代 demoparser2 补丁）：enemy_blind_s / team_blind_s / 敌方中位数 / 闪光浪费率
- ✅ 分道具购买 vs 使用率 usage（item_events purchase × grenades 投掷，incendiary 合火）：{bought, thrown, waste_rate}；真实 demo 实测 **molotov 浪费率 0.5 为最短板**；详情 Drawer 浪费 ≥30% 红标
- ✅ 覆盖率门禁恢复：二期欠账 84.7% → **90.09%**（补 bili_learn 编排 / bili_api / ai_client provider 分支 / chat 边界契约）

### ✅ P1：AI 复盘深度
- ✅ 经济复盘（round_economy × rounds join）：eco_win_rate（抗压）/ full_buy_lose_rate（资源转化）+ 满编败率 >50% 硬红线（report.py 红线序：近战 > 经济 > 道具 > 劣势枪位）；真实 demo eco 1.0 / 满编败 0.222
- ✅ 对枪口径补全（damages 交火窗口，击杀切窗）：first_strike_win_rate / mirror_win_rate 补二期 null；真实 demo 0.5 / 0.667
- ✅ 高光检测 `services/highlight.py`（借鉴 cs2-highlights-maker 评分思路纯解析版）：回合内 >20s 击杀聚类 → 评分（kills×2+爆头+特殊击杀+多杀加成+胜局+残局起点）→ Top5；真实 demo 检出 R15 残局双杀(6分)；详情 Drawer 高光表（残局🔥标记）

### ✅ P2：可视化与长期追踪
- ✅ 道具落点 `collect_utility_spots`：user 侧烟/火落点 + 相关致盲被闪位置；前端 UtilityScatter 组件（复用雷达底图与官方坐标映射，三色散点）
- ✅ 长期追踪端点 `GET /api/matches/stats/trends`（逐场聚合点 + 地图胜率）+ 前端「趋势」Tab（rating/ADR 逐场折线 + 道具指标趋势 + 地图胜率条形）
- ✅ 重复死亡模式 `services/death_patterns.py`：跨场 500unit(≈9.5m) 网格聚合 ≥3 次 → 周报「惯性死亡点」段落 + AI 教练上下文注入

### 验收证据（2026-11-23）
- 后端全量 pytest 全绿，覆盖率 **90.09%** ≥ 87% 门禁（只升不降，下修基线待用户确认）
- 真实 demo（9217780881059103244，dust2，64tick）端到端：SCHEMA 1.1 四维 + usage + highlights + spots 全部产出，3.9-4.6s/1MB 峰值内存
- Mock 全链路（worktree 服务 8102 + 主库数据目录）：`pushed: true, mv_uuid=12642d38…`（SCHEMA 1.1 payload 真实推送 MindVault）
- 前端 `tsc --noEmit` PASS + `npm run build` PASS（趋势 Tab / 道具散点 / 高光表 / 指标卡四项 UI）

### Backlog（三期未做，记录待后续）
- HLAE + mirv_streams 全自动高光录制（cs2-highlights-maker 方案：Windows+CS2 满足，但需 -insecure 沙箱且 HLAE 需跟随 CS2 版本，禁 VAC 服务器）
- 2D 回放动画（cs-demo-manager 式 awpy snapshots 逐 tick 采样）
- 弱道具 → B站自动检索教学闭环（死亡模式点位 → 关键词 → cs2-learn；CS2HQ 独有优势方向）
- GitHub 私有仓库推送（待 gh auth login 后执行：gh repo create yingdijiudanche/cs2hq --private --source . --push）

## 禁区与回滚

- **禁区**：不做客户端注入；不批量爬 B站、不公开端点文档；凭证加密不进 git；不改 MindVault 除 capture/videos 外代码；完美平台限速 ≥2s、401/403 必熔断。
- **回滚**：demo 下载失败 → pending_demo；解析失败/超内存 → 降级仅 API 数据复盘；模型输出非法 → 重试 1 次 → 纯文本；无字幕 → no_subtitle；时刻压缩后仍超限 → 封面+链接卡片。
- **人工接管点**：token 失效（NEED_AUTH）、B站风控 ≥1h、完美平台接口变更（暂停 loop + 面板报警）。

## 主要风险

1. B站风控 → 软着陆。2. demo 解析耗时/内存 → 按需提取 + 分块 + Semaphore(1) + API 兜底。3. token 轮换 → NEED_AUTH + 快速更新 + Fernet。4. 磁盘膨胀 → 解析后删 raw、上传后删本地、定时 GC。

预计总工期 5-6 天；每阶段结束交付可验收物。
