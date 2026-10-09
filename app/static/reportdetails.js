/* reportdetails.js — the models against your reports (step W3).
 *
 * The section the Details card renders right after the station's accuracy
 * table, from the ``user_reports`` block of /api/model-accuracy:
 *   - "Against your reports" (report.acc-title) as the title,
 *   - without scored reports: the "no reports yet" line (acc-none),
 *   - otherwise: the hours/confirmed line (acc-summary), a table like the
 *     station's — one row per model (best hit rate first, same columns
 *     without the mae), and the note (acc-note) explaining what counts.
 *
 * Pure DOM builder: the data comes in as arguments, so the renderer and
 * the section can fail independently like the other Details sections.
 */
import { t } from "./i18n.js";
import { DASH, fmtPercent, modelLabel, sortAccuracy } from "./format.js";

/* The user_reports block ({hours, confirmed_hours, models}) or null. */
function userReports(accuracy) {
  const ur = accuracy && accuracy.user_reports;
  return ur && typeof ur === "object" ? ur : null;
}

/* The section's div with its title (the Details card's own section look). */
function reportsDiv(title) {
  const div = document.createElement("div");
  div.className = "details-section";
  div.setAttribute("data-test", "accuracy-reports");
  const h = document.createElement("h3");
  h.textContent = title;
  div.appendChild(h);
  return div;
}

export function reportsSection(accuracy, lang, locale) {
  const sec = reportsDiv(t(lang, "report.acc-title"));
  const ur = userReports(accuracy);
  const models = ur && ur.models && typeof ur.models === "object"
    ? ur.models
    : {};
  if (Object.keys(models).length === 0) {
    const none = document.createElement("p");
    none.className = "accuracy-no-rain";
    none.setAttribute("data-test", "accuracy-reports-none");
    none.textContent = t(lang, "report.acc-none");
    sec.appendChild(none);
    return sec;
  }
  const summary = document.createElement("p");
  summary.className = "reports-summary";
  summary.setAttribute("data-test", "accuracy-reports-summary");
  summary.textContent = t(lang, "report.acc-summary", {
    hours: ur.hours,
    confirmed: ur.confirmed_hours,
  });
  sec.appendChild(summary);
  sec.appendChild(reportsTable(models, lang, locale));
  const note = document.createElement("p");
  note.className = "accuracy-note";
  note.setAttribute("data-test", "accuracy-reports-note");
  note.textContent = t(lang, "report.acc-note");
  sec.appendChild(note);
  return sec;
}

/* Like buildTable in details.js but without the mae column: the reports
 * have no measured precipitation to compare. */
function reportsTable(models, lang, locale) {
  const scroll = document.createElement("div");
  scroll.className = "table-scroll";
  const table = document.createElement("table");
  table.className = "accuracy-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.setAttribute("data-test", "accuracy-reports-head");
  for (const key of ["model", "hours", "hits", "misses", "false-alarms", "hit-rate"]) {
    const th = document.createElement("th");
    th.textContent = t(lang, `accuracy.head.${key}`);
    headRow.appendChild(th);
  }
  head.appendChild(headRow);
  table.appendChild(head);
  const body = document.createElement("tbody");
  for (const name of sortAccuracy(models)) {
    const m = models[name];
    const row = document.createElement("tr");
    row.setAttribute("data-test", "accuracy-reports-row");
    row.setAttribute("data-model", name);
    const cells = [
      modelLabel(name),
      m.n_samples,
      m.hits,
      m.misses,
      m.false_alarms,
      fmtPercent(typeof m.event_accuracy === "number" ? m.event_accuracy * 100 : null, locale),
    ];
    for (const c of cells) {
      const td = document.createElement("td");
      td.textContent = c == null ? DASH : String(c);
      row.appendChild(td);
    }
    body.appendChild(row);
  }
  table.appendChild(body);
  scroll.appendChild(table);
  return scroll;
}
