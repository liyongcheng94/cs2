// 极薄 API 封装：统一 /api 前缀与错误抛出
export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`);
  if (!resp.ok) throw new Error(`GET ${path}: HTTP ${resp.status}`);
  return resp.json();
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`PUT ${path}: HTTP ${resp.status}`);
  return resp.json();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`POST ${path}: HTTP ${resp.status}`);
  return resp.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(`DELETE ${path}: HTTP ${resp.status}`);
  return resp.json();
}
