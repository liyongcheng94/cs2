// 探针：验证 e2e.config.ts 里的 docker exec 取 key 路径
import { execSync } from "node:child_process";

const PY = [
  "from app.database import get_engine",
  "from app.services.settings_service import get_all",
  "from sqlmodel import Session",
  "with Session(get_engine()) as s:",
  "    print(get_all(s).get('ai.api_key.deepseek',''))",
].join("\n");

const cmd = `docker exec mindvault-app-1 sh -c "cd /app && python <<'PYEOF'\n${PY}\nPYEOF"`;
const out = execSync(cmd, { encoding: "utf8", timeout: 15000 }).trim();
console.log("key head:", out.slice(0, 6), "len:", out.length);
