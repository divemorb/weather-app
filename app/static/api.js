/* api.js — the page's fetch helpers, shared by app.js and setup.js.
 *
 * Non-2xx responses throw ApiError; the page decides what a failure means
 * (keep the old content, show a status).
 */

/* A non-2xx response; `detail` carries the API's error body, if any. */
export class ApiError extends Error {
  constructor(path, status, detail) {
    super(`${path} -> ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function json(res, path) {
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(path, res.status, data && data.detail);
  return data;
}

/* Throws ApiError on non-2xx. */
export async function getJSON(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  return json(res, path);
}

/* Throws ApiError on non-2xx. */
export async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return json(res, path);
}
