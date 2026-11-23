// 统一 API 基路径：默认 "/"（本地 dev / 独立域名），路径前缀部署（will-site /cs2hq/）时
// 通过 vite base 注入 BASE_URL="/cs2hq/"，fetch 自动带上前缀，避免漏到同域其他应用的 /api。
const BASE = import.meta.env.BASE_URL || "/";
const API = BASE.endsWith("/") ? `${BASE}api` : `${BASE}/api`;

// 极薄 API 封装：统一 /api 前缀与错误抛出
export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API}${path}`);
  if (!resp.ok) throw new Error(`GET ${path}: HTTP ${resp.status}`);
  return resp.json();
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`PUT ${path}: HTTP ${resp.status}`);
  return resp.json();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`POST ${path}: HTTP ${resp.status}`);
  return resp.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(`${API}${path}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(`DELETE ${path}: HTTP ${resp.status}`);
  return resp.json();
}
