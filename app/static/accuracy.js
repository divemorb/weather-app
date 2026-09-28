/* "Model accuracy" card (step 6f).
 *
 * Fetches GET /api/model-accuracy (per-model forecast accuracy over the
 * configured window, see README → "Scoring the models") and renders a small
 * comparison table. Loaded before app.js via a <script> tag; exposes the
 * global renderAccuracyCard() which app.js calls on each refresh.
 *
 * States:
 *   - no models compared yet   -> "no data yet" line
 *   - nothing at min_samples   -> "Collecting data — N of M hours"
 *   - otherwise                -> table; rows below min_samples are greyed out
 *
 * Uses the shared helpers from app.js (els, getJSON, fmtNum); no build step,
 * no external CDN.
 */
"use strict";

const ACCURACY_HEADERS = ["Model", "Samples", "Hit", "Miss", "False alarm", "Event acc.", "MAE"];

function _accPct(v) {
  return v == null || isNaN(v) ? "—" : `${Math.round(v * 100)} %`;
}

/**
 * Fetch and render the model-accuracy card. Never throws: a failing request
 * must not break the other cards (a failing source never blocks the app).
 */
async function renderAccuracyCard() {
  els.accuracyTable.innerHTML = "";
  try {
    const data = await getJSON("/api/model-accuracy");
    els.accuracyBadge.hidden = false;
    els.accuracyBadge.textContent = `${data.window_days} d window`;

    const models = data.models || {};
    const names = Object.keys(models);
    if (names.length === 0) {
      els.accuracyStatus.hidden = false;
      els.accuracyStatus.textContent =
        "No data yet — observations are compared hourly.";
      return;
    }

    const enough = names.filter((n) => models[n].enough_data).length;
    if (enough === 0) {
      const maxN = Math.max(...names.map((n) => models[n].n_samples || 0));
      els.accuracyStatus.hidden = false;
      els.accuracyStatus.textContent =
        `Collecting data — ${maxN} of ${data.min_samples} hours`;
    } else {
      els.accuracyStatus.hidden = true;
    }
    els.accuracyTable.appendChild(buildAccuracyTable(data));
  } catch (e) {
    console.error("model-accuracy:", e);
    els.accuracyBadge.hidden = true;
    els.accuracyStatus.hidden = true;
    els.accuracyTable.innerHTML =
      '<span class="muted">Could not load model accuracy.</span>';
  }
}

/** Build the accuracy comparison table from the API payload. */
function buildAccuracyTable(data) {
  const names = Object.keys(data.models || {});
  const table = document.createElement("table");
  table.className = "accuracy-table";

  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const h of ACCURACY_HEADERS) {
    const th = document.createElement("th");
    th.textContent = h;
    headRow.appendChild(th);
  }
  head.appendChild(headRow);
  table.appendChild(head);

  const body = document.createElement("tbody");
  for (const name of names) {
    const m = data.models[name];
    const row = document.createElement("tr");
    if (!m.enough_data) row.className = "low";

    const cells = [
      { text: name, cls: "acc-model" },
      { text: `${m.n_samples}`, cls: "num" },
      { text: `${m.hits}`, cls: "num" },
      { text: `${m.misses}`, cls: "num" },
      { text: `${m.false_alarms}`, cls: "num" },
      { text: _accPct(m.event_accuracy), cls: "num acc-acc" },
      { text: m.mae_mm != null ? `${fmtNum(m.mae_mm, 2)} mm` : "—", cls: "num" },
    ];
    for (const c of cells) {
      const td = document.createElement("td");
      td.className = c.cls;
      td.textContent = c.text;
      row.appendChild(td);
    }
    body.appendChild(row);
  }
  table.appendChild(body);
  return table;
}
