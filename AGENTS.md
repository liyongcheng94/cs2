# CS2HQ 工作区规则：TDD + BDD（强制执行）

> ZCode 工作区级指令，每次会话自动加载。规则源自 MindVault 项目实践（同栈同规范）。

## 0. 项目速览（必读）

| 项 | 说明 |
|------|------|
| 定位 | 专属 CS2 提升平台：完美平台战绩 + demo 四维解析 + B站学习 + 完美时刻，全自动推送 MindVault |
| 架构 | `backend/`（FastAPI + SQLModel + SQLite，入口 `app/main.py`，DB 在 `data/cs2hq.db`）+ `frontend/`（React + antd + Vite） |
| 后端端口 | `127.0.0.1:8100`（dev，uvicorn） |
| 前端端口 | `5174`（vite dev，/api 代理到 8100） |
| 计划文档 | `ARCHITECTURE.md`（v5 终版，每阶段完成打勾附验收证据） |
| Python | 3.12（uv 管理的 CPython 3.12.12；`py -V:Astral/CPython3.12.12 -m venv .venv`） |

**常用命令**（Windows / Git Bash）：

```bash
# 后端全量测试 + 覆盖率门禁（只升不降，基线见下）
cd backend && .venv/Scripts/python.exe -m pytest --cov=app --cov-fail-under=<基线>
# 前端类型检查 / 构建
cd frontend && npx tsc --noEmit && npm run build
# 一键验收（含 Mock 全链路检查）
python verify.bat
```

**Mock 全链路（每日收工前必跑）**：MindVault 启动后（dev: 8001）`curl -X POST http://127.0.0.1:8100/api/test/mock-flow` 应返回 `pushed: true` 且 MindVault `curl "http://127.0.0.1:8001/api/search?q=CS2HQ"` 能命中。

## 1. 场景先行（BDD）

- 任何功能、修复或重构需求，第一步是写出行为场景
- 使用 **Given / When / Then** 写在测试函数的 docstring 中
- 场景必须覆盖：正常路径、边界条件、错误处理、关键业务规则
- **绝不允许**"先实现，后补场景"

## 2. 测试严格先行（TDD）

- 场景定义后，**立即**编写 pytest 测试函数 → 运行确认失败（Red）→ 最小实现（Green）→ 重构（Refactor）
- 一次只改一处，改完立刻运行测试

## 3. 最小实现

- 绝不允许提前设计未来才需要的代码，只解决当前场景
- 禁止添加场景未覆盖的"额外"功能

## 工具与项目约定

| 项 | 约定 |
|------|------|
| 后端框架 | FastAPI + SQLModel + SQLite；日志 loguru（必须带 trace 字段：matchId/taskId/bvid） |
| 凭证存储 | settings 表内 Fernet 加密（`services/crypto.py`）；secret.key 走环境变量 `CS2HQ_SECRET_KEY`，绝不入 git |
| 数据访问 | 一律经 services 层；JSON 高级查询服务端预计算；未来迁 PostgreSQL 仅换引擎（SQLModel 接口不变） |
| CPU 密集任务 | demo 解析 / ffmpeg 一律 `asyncio.to_thread()` + `Semaphore(1)`，严禁卡事件循环 |
| 完美平台 | 限速 ≥2s；401/403 立即熔断任务状态 NEED_AUTH，严禁后台重试 |
| B 站 | 限速 1s/视频；风控码 -412/-352/10031/12051/12015 → 暂停对应任务 ≥1h |
| 测试目录 | backend/tests/test_\<模块名\>.py；共享夹具 backend/tests/conftest.py（DATA_DIR 指向临时目录） |
| 前端测试 | vitest + Testing Library；场景写在 describe/test 名与注释中 |
| 覆盖率基线 | 首测值 -5% 写入此处，`--cov-fail-under` 只升不降。**基线：87%**（2026-11-22 二次修订：阶段1-4 新增 wanmei/bili/moments 三个网络凭证模块，纯网络路径不可本地覆盖；由首版 94%(21用例/607语句) → 87%(80用例/1617语句)，新基线只升不降） |
| 依赖锁版 | requirements.txt 全部 `==` 精确版本（pip freeze），新增依赖同样锁死 |
| 提交规范 | 每功能点三段 commit：`RED: <描述>` / `GREEN: <描述>` / `REFACTOR: <描述>`；夜任务可加前缀 `night(N):` |

## 绝对禁止的行为

- ❌ 在没有场景的情况下写任何测试或实现代码
- ❌ 说"这个改动很小，不需要场景"或"测试后面补"
- ❌ 跳过 Red 阶段直接提交实现代码
- ❌ 在测试失败时继续写实现，不修复失败
- ❌ 添加场景未覆盖的"额外"功能
- ❌ 先写实现再补测试
- ❌ 凭证明文落库或入 git
- ❌ 对完美平台 401/403 做后台自动重试

## 适应性说明

- 需求不足以写出具体场景时，**先提问明确验收条件**，绝不猜着写实现
- 任何偏离 TDD 流程必须征得用户明确同意，并解释原因
