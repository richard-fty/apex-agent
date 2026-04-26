/** Thin fetch wrapper. Cookies carry auth; same-origin via Vite proxy. */

export interface ApiError extends Error {
  status: number;
}

async function handle(res: Response): Promise<Response> {
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.clone().json();
      if (body?.detail) message = body.detail;
    } catch { /* ignore */ }
    const err = new Error(message) as ApiError;
    err.status = res.status;
    throw err;
  }
  return res;
}

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "include" });
  await handle(res);
  return res.json();
}

export async function getJSONOrNull<T>(path: string): Promise<T | null> {
  const res = await fetch(path, { credentials: "include" });
  if (res.status === 404) return null;
  await handle(res);
  return res.json();
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await handle(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? JSON.parse(text) : (undefined as T);
}

export async function del(path: string): Promise<void> {
  const res = await fetch(path, { method: "DELETE", credentials: "include" });
  await handle(res);
}
