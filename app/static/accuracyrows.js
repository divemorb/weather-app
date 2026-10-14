/* accuracyrows.js — the body of the two accuracy tables.
 *
 * The station's accuracy table (details.js) and the models-against-your-
 * reports table (reportdetails.js) share one row per model: the same
 * columns — model, samples, hits, misses, false alarms, hit rate — the
 * same order (best hit rate first, the rows without enough data last)
 * and the same cell rendering (a dash for a missing value). This module
 * is the identical <tbody> of both; the heads stay with the callers
 * (the reports' table has no mae column) and so do the rows' data-test
 * names and the greying, which only the station's table has.
 */
import { DASH, fmtPercent, modelLabel, sortAccuracy } from "./format.js";

/* One row per model in the <tbody>: `rowTest` is the rows' data-test,
 * `low` greys the rows below the sample minimum (the station's table),
 * and `extra` — a function of the model, or null — adds a cell after
 * the hit rate (the mae in the station's table, nothing in the reports'). */
export function accuracyRows(models, locale, rowTest, low, extra) {
  const body = document.createElement("tbody");
  for (const name of sortAccuracy(models)) {
    const m = models[name];
    const row = document.createElement("tr");
    row.setAttribute("data-test", rowTest);
    row.setAttribute("data-model", name);
    if (low && !m.enough_data) row.className = "low";
    const cells = [
      modelLabel(name),
      m.n_samples,
      m.hits,
      m.misses,
      m.false_alarms,
      fmtPercent(typeof m.event_accuracy === "number" ? m.event_accuracy * 100 : null, locale),
    ];
    if (extra) cells.push(extra(m));
    for (const c of cells) {
      const td = document.createElement("td");
      td.textContent = c == null ? DASH : String(c);
      row.appendChild(td);
    }
    body.appendChild(row);
  }
  return body;
}
