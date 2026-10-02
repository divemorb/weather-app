/* api.js — the page's fetch helpers (step W2).
 *
 * Shared by app.js and setup.js (a small module on purpose, so the two do
 * not import from each other). Non-2xx responses throw ApiError; the page
 * decides what a failure means (keep the old content, show a status).
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

/* GET expecting JSON; throws ApiError on non-2xx. */
export async function getJSON(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  return json(res, path);
}

/* POST a JSON body; throws ApiError (status, detail) on non-2xx. */
export async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return json(res, path);
}
