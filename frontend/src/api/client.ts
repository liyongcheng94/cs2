// 统一 API 基路径：默认 "/"（本地 dev / 独立域名），路径前缀部署（will-site /cs2hq/）时
// 通过 vite base 注入 BASE_URL="/cs2hq/"，fetch 自动带上前缀，避免漏到同域其他应用的 /api。
const BASE = import.meta.env.BASE_URL || "/";
const API = BASE.endsWith("/") ? `${BASE}api` : `${BASE}/api`;

// 401 统一处理：任意 API 返回 401（登录失效）时派发全局事件，
// App 层监听并切回登录页（账号体系 Phase 2）。
function handleUnauthorized() {
  window.dispatchEvent(new CustomEvent("cs2hq:unauthorized"));
}

async function check(resp: Response, method: string, path: string): Promise<Response> {
  if (resp.status === 401) {
    handleUnauthorized();
    throw new Error(`${method} ${path}: HTTP 401`);
  }
  if (!resp.ok) throw new Error(`${method} ${path}: HTTP ${resp.status}`);
  return resp;
}

// 极薄 API 封装：统一 /api 前缀与错误抛出
export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API}${path}`);
  await check(resp, "GET", path);
  return resp.json();
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await check(resp, "PUT", path);
  return resp.json();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  await check(resp, "POST", path);
  return resp.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(`${API}${path}`, { method: "DELETE" });
  await check(resp, "DELETE", path);
  return resp.json();
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await check(resp, "PATCH", path);
  return resp.json();
}

// multipart 文件上传（道具卡贴图 / 自建道具）：可带额外字段；不设 Content-Type（浏览器自动带 boundary）
export async function apiUpload<T>(path: string, files: File[], extra?: Record<string, string>): Promise<T> {
  const form = new FormData();
  for (const [k, v] of Object.entries(extra ?? {})) {
    if (v) form.append(k, v);
  }
  for (const f of files) form.append("files", f);
  const resp = await fetch(`${API}${path}`, { method: "POST", body: form });
  await check(resp, "POST", path);
  return resp.json();
}
