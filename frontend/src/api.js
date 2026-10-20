export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function parseError(body, fallback) {
  if (!body) return fallback;
  if (typeof body.detail === "string") return body.detail;
  if (typeof body.detail === "object" && body.detail !== null) {
    if (Array.isArray(body.detail.errors)) {
      return body.detail.errors.join("; ");
    }
    if (body.detail.errors) return String(body.detail.errors);
  }
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  }
  if (body.message) return body.message;
  return fallback;
}

export async function get(path) {
  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new Error("Backend unreachable. Is the API running on port 8000?");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(parseError(body, res.statusText));
  }
  return res.json();
}

export async function post(path, body) {
  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Backend unreachable. Is the API running on port 8000?");
  }
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new Error(parseError(b, res.statusText));
  }
  return res.json();
}

export async function patch(path, body) {
  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Backend unreachable. Is the API running on port 8000?");
  }
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new Error(parseError(b, res.statusText));
  }
  return res.json();
}

export async function del(path, body) {
  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Backend unreachable. Is the API running on port 8000?");
  }
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new Error(parseError(b, res.statusText));
  }
  return res.json();
}
