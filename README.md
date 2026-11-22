# CS2HQ — 专属 CS2 提升平台

完美平台战绩自动拉取 · demo 四维解析复盘 · B站教学视频总结 · 完美时刻下载，全部自动沉淀到 [MindVault](../MindVault) 公网知识库。

**计划与进度**：[ARCHITECTURE.md](ARCHITECTURE.md)（v5 终版）· **工作区规则**：[AGENTS.md](AGENTS.md)

## 结构

```
cs2/
├── backend/          # FastAPI + SQLModel + SQLite（端口 8100）
│   └── app/{api,services,models.py,config.py,database.py,main.py}
├── frontend/         # React + antd + Vite（端口 5174，/api → 8100）
├── data/             # 运行时数据（.gitignore）
└── verify.bat        # 一键验收
```

## 快速开始

```bash
# 后端
py -V:Astral/CPython3.12.12 -m venv backend/.venv
backend/.venv/Scripts/pip install -r backend/requirements.txt
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --port 8100   # cwd=backend

# 前端
cd frontend && npm install && npm run dev   # http://localhost:5174
```

MindVault（推送目标）需在 8001（dev）运行；凭证（完美平台 token / B站 SESSDATA / MindVault 密码）在面板「设置」页粘贴，Fernet 加密落库。
