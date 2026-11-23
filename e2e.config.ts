import type { E2EConfig } from "e2e";
import { web } from "@e2e-dev/web";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { execSync } from "node:child_process";

// DeepSeek key：从 MindVault 后端容器 settings 表读（运行时获取，不入库不入 git）
function deepseekKey(): string {
  const env = process.env.DEEPSEEK_API_KEY;
  if (env) return env;
  try {
    const PY = [
      "from app.database import get_engine",
      "from app.services.settings_service import get_all",
      "from sqlmodel import Session",
      "with Session(get_engine()) as s:",
      "    print(get_all(s).get('ai.api_key.deepseek',''))",
    ].join("\n");
    const cmd = `docker exec mindvault-app-1 sh -c "cd /app && python <<'PYEOF'\n${PY}\nPYEOF"`;
    return execSync(cmd, { encoding: "utf8", timeout: 15000 }).trim();
  } catch {
    return "";
  }
}

const deepseek = createOpenAICompatible({
  name: "deepseek",
  baseURL: "https://api.deepseek.com/v1",
  apiKey: deepseekKey(),
});

export default {
  tests: "tests/**/*.e2e.ts",
  targets: [
    {
      // 已运行的 docker 栈：cs2hq-frontend(127.0.0.1:5174, nginx 反代 /api → backend:8101)
      engine: web(),
      app: { url: "http://127.0.0.1:5174" },
    },
  ],
  agents: {
    default: {
      model: deepseek.chatModel("deepseek-flash"),
      system:
        "你是严格的 QA 测试代理，测试 CS2HQ（CS2 战绩提升平台，中文 antd 界面）。" +
        "界面用 antd Tabs 顶部导航：总览/对局/趋势/学道具/AI 教练/任务/设置。" +
        "每个 act 只做一个小目标；assert 前先看清页面实际内容，不要凭空想象文案。",
    },
  },
  timeout: 180000,
  workers: 1,
} satisfies E2EConfig;
