// The responsive sweep's probe (responsive.py calls it with its settings): every invariant at the current size, as [invariant, detail] pairs.
((cfg) => {
  const out = [];
  const de = document.documentElement, W = de.clientWidth, H = de.clientHeight;
  const vis = (el) => el.checkVisibility({ visibilityProperty: true, opacityProperty: true });
  const name = (el) => (el.dataset && el.dataset.test ? "[data-test=" + el.dataset.test + "]"
    : el.id ? "#" + el.id : el.tagName.toLowerCase() + (typeof el.className === "string" && el.className
      ? "." + el.className.trim().split(/\s+/)[0] : ""));
  const box = (r) => Math.round(r.left) + "," + Math.round(r.top) + " to " + Math.round(r.right) + "," + Math.round(r.bottom);
  if (de.scrollWidth > W + 1) out.push(["h-scroll", "the page is " + de.scrollWidth + " px wide in a " + W + " px window"]);
  for (const el of [de, document.body]) {
    const o = getComputedStyle(el).overflowY;
    if (el.scrollHeight > H + 1 && (o === "hidden" || o === "clip"))
      out.push(["cut-off", name(el) + " has overflow-y " + o + " but is " + el.scrollHeight + " px high in a " + H + " px window"]);
  }
  const sky = document.getElementById("sky");
  if (sky) {
    const r = sky.getBoundingClientRect();
    if (r.left > 0.5 || r.top > 0.5 || r.right < W - 0.5 || r.bottom < H - 0.5)
      out.push(["sky", "the sky covers " + box(r) + ", not the " + W + "x" + H + " window"]);
  }
  const cards = [...document.querySelectorAll(".wrap .card, .topbar, .wrap > .attr")].filter(vis)
    .filter((c) => !c.parentElement.closest(".card"));
  const rects = cards.map((c) => c.getBoundingClientRect());
  cards.forEach((c, i) => {
    const r = rects[i];
    if (r.width === 0 || r.height === 0) return;
    if (r.left < -1 || r.right > W + 1) out.push(["outside", name(c) + " (" + box(r) + ") outside the " + W + " px window"]);
    for (let j = i + 1; j < cards.length; j++) {
      const q = rects[j];
      const ox = Math.min(r.right, q.right) - Math.max(r.left, q.left), oy = Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top);
      if (ox > 1 && oy > 1) out.push(["overlap", name(c) + " (" + box(r) + ") over " + name(cards[j]) + " (" + box(q) + ")"]);
    }
    const scrollers = [...c.querySelectorAll("*")].filter((el) => /auto|scroll/.test(getComputedStyle(el).overflowX));
    for (const el of c.querySelectorAll("*")) {  // a scroll box's content may be wider: it scrolls
      if (!vis(el) || el.closest("svg") && el.tagName.toLowerCase() !== "svg") continue;
      if (scrollers.some((s) => s !== el && s.contains(el))) continue;
      const b = el.getBoundingClientRect();
      if (b.width === 0 || b.height === 0) continue;
      if (b.left < r.left - 1 || b.top < r.top - 1 || b.right > r.right + 1 || b.bottom > r.bottom + 1) {
        out.push(["spill", name(el) + " (" + box(b) + ") reaches outside " + name(c) + " (" + box(r) + ")"]);
        break;
      }
    }
    for (const el of c.querySelectorAll("*")) {  // inside a clipping box but beyond it: cut off
      if (!vis(el) || el.closest("svg")) continue;
      const o = getComputedStyle(el);
      if (!/hidden|clip/.test(o.overflowX + o.overflowY)) continue;
      if (el.scrollHeight > el.clientHeight + 1 && /hidden|clip/.test(o.overflowY) ||
          el.scrollWidth > el.clientWidth + 1 && /hidden|clip/.test(o.overflowX))
        out.push(["clipped", name(el) + " cuts off its content (" + el.scrollWidth + "x" + el.scrollHeight
                  + " in " + el.clientWidth + "x" + el.clientHeight + ")"]);
    }
  });
  const answerEl = document.querySelector('[data-test="rain-answer"]');
  const answer = answerEl && vis(answerEl) ? parseFloat(getComputedStyle(answerEl).fontSize) : 0;
  const display = cfg.display.map((h) => document.querySelector('[data-test="' + h + '"]')).filter(Boolean);
  const walker = document.createTreeWalker(document.querySelector(".wrap") || document.body, NodeFilter.SHOW_TEXT);
  const small = [], larger = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || !el || !vis(el)) continue;
    let px = parseFloat(getComputedStyle(el).fontSize);
    const svg = el.closest("svg");
    if (svg) {
      const vb = svg.viewBox && svg.viewBox.baseVal;
      if (vb && vb.width) px *= svg.getBoundingClientRect().width / vb.width;
    }
    const min = el.closest(cfg.fine) ? cfg.fineMin : cfg.textMin;
    if (px < min - 0.05) small.push(name(el) + " " + px.toFixed(1) + " px (at least " + min + ")");
    if (answer && px > answer + 0.05 && el !== answerEl && !display.some((d) => d.contains(el)))
      larger.push(name(el) + " " + px.toFixed(1) + " px");
  }
  if (small.length) out.push(["text-size", small.length + " texts too small: " + [...new Set(small)].slice(0, 4).join("; ")]);
  if (larger.length) out.push(["hierarchy", "the headline is " + answer.toFixed(1) + " px, larger: " + [...new Set(larger)].slice(0, 3).join("; ")]);
  if (answer && W < cfg.narrow) {  // the user's rule: a narrow page's headline in at most two lines
    const range = document.createRange();
    range.selectNodeContents(answerEl);
    const lines = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.bottom))).size;
    if (lines > cfg.lines) out.push(["headline-lines", "the headline takes " + lines + " lines in a " + W + " px window, at most " + cfg.lines]);
  }
  for (const sel of cfg.rows) {
    const rs = [...document.querySelectorAll(sel)].filter(vis).map((e) => e.getBoundingClientRect())
      .filter((r) => r.width > 0).sort((a, b) => a.left - b.left);
    for (let i = 1; i < rs.length; i++) {
      if (rs[i].left < rs[i - 1].right + cfg.gap && Math.abs(rs[i].top - rs[i - 1].top) < rs[i].height) {
        out.push(["labels", sel + ": two labels " + Math.round(rs[i - 1].right - rs[i].left + cfg.gap) + " px too close"]);
        break;
      }
    }
  }
  for (const svg of document.querySelectorAll('svg[data-test="chart"]')) {  // drawn 1:1, never scaled
    const vb = svg.viewBox.baseVal, r = svg.getBoundingClientRect();
    if (vis(svg) && (Math.abs(vb.width - r.width) > 1 || Math.abs(vb.height - r.height) > 1))
      out.push(["chart-scale", "the chart is drawn at " + vb.width + "x" + vb.height + " but shown at "
                + Math.round(r.width) + "x" + Math.round(r.height) + " (not redrawn for its box)"]);
  }
  const hours = [...document.querySelectorAll('[data-test="chart-x-label"]')].filter(vis).length;
  const chart = document.querySelector('svg[data-test="chart"]');
  if (chart && vis(chart) && hours < cfg.minHours)
    out.push(["chart-hours", "the chart shows " + hours + " hour labels, at least " + cfg.minHours]);
  if (de.dataset.view === "detailed") {  // the details card is as wide as the top bar, edge to edge
    const card = document.querySelector('[data-test="details"]').getBoundingClientRect();
    const bar = document.querySelector(".topbar").getBoundingClientRect();
    if (Math.abs(card.left - bar.left) > 1 || Math.abs(card.right - bar.right) > 1)
      out.push(["details-width", "the details card spans " + Math.round(card.left) + " to " + Math.round(card.right)
                + " px, the top bar " + Math.round(bar.left) + " to " + Math.round(bar.right)]);
  }
  for (const map of document.querySelectorAll('svg[data-test="station-map"]')) {  // every name readable: no text on another, on a symbol or past the edge
    if (!vis(map)) continue;
    const mb = map.getBoundingClientRect(), hit = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5
      && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5;
    const said = (el) => '"' + el.textContent.trim().slice(0, 30) + '"';
    const texts = [...map.querySelectorAll("text")].map((el) => [el, el.getBoundingClientRect()]);
    const marks = [...map.querySelectorAll(".map-mark, .map-loc, .map-north path, .map-scale line")]
      .map((el) => [el, el.getBoundingClientRect()]);
    const bad = [];
    texts.forEach(([a, r], i) => {
      for (const [b, q] of texts.slice(i + 1)) if (hit(r, q)) bad.push(said(a) + " on " + said(b));
      for (const [m, q] of marks)  // a symbol's own text (N under the arrow, the scale's km) belongs to it
        if (hit(r, q) && !(m.parentNode === a.parentNode && a.parentNode !== map))
          bad.push(said(a) + " on " + (m.classList.contains("map-mark") ? "the mark of " + said(m) : name(m)));
      if (r.left < mb.left - 0.5 || r.top < mb.top - 0.5 || r.right > mb.right + 0.5 || r.bottom > mb.bottom + 0.5)
        bad.push(said(a) + " past the map's edge");
    });
    if (bad.length) out.push(["map-labels", bad.slice(0, 3).join("; ")]);
  }
  const styles = Object.fromEntries(cfg.styles.map((st) => [st, parseFloat(getComputedStyle(document.body).getPropertyValue("--t-" + st))]));
  const sizes = Object.values(styles).filter((v) => v > 0);
  if (sizes.length < cfg.styles.length) out.push(["type-scale", "the page has no type scale (--t-<style> on body): " + JSON.stringify(styles)]);
  else {
    const off = [], tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent.trim() || !el || !vis(el) || el.closest("script, style")) continue;
      const svg = el.closest("svg");  // a drawing's text counts when it is drawn 1:1 (the chart), not scaled (the map)
      if (svg && (!svg.viewBox.baseVal || Math.abs(svg.viewBox.baseVal.width - svg.getBoundingClientRect().width) > 1)) continue;
      const px = parseFloat(getComputedStyle(el).fontSize);
      if (!sizes.some((v) => Math.abs(v - px) < 0.3)) off.push(name(el) + " " + px.toFixed(1) + " px");
    }
    if (off.length) out.push(["type-scale", off.length + " texts off the scale (" + sizes.map((v) => v.toFixed(1)).join("/") + " px): " + [...new Set(off)].slice(0, 4).join("; ")]);
    const wrong = [];
    for (const [st, sels] of Object.entries(cfg.roles))
      for (const el of document.querySelectorAll(sels.join(",")))
        if (vis(el) && el.textContent.trim() && Math.abs(parseFloat(getComputedStyle(el).fontSize) - styles[st]) >= 0.3)
          wrong.push(name(el) + " " + parseFloat(getComputedStyle(el).fontSize).toFixed(1) + " px, not " + st + " " + styles[st].toFixed(1));
    if (wrong.length) out.push(["type-roles", [...new Set(wrong)].slice(0, 4).join("; ")]);
  }
  const brand = document.querySelector(".topbar .brand"), acts = document.querySelector(".topbar .actions");
  if (brand && acts && vis(acts) && acts.getBoundingClientRect().top >= brand.getBoundingClientRect().bottom - 1)
    out.push(["bar-one-row", "the bar's buttons wrapped under the place (" + box(acts.getBoundingClientRect()) + ")"]);
  for (const c of __ui.controls()) out.push(["buttons", c]);
  const ctrls = [...document.querySelectorAll("button, [role='button'], a[href], input, select")]
    .filter((el) => vis(el) && !el.closest("[inert]"))  // an inert control (under the open picker) can't be used
    .map((el) => [el, el.getBoundingClientRect()]).filter(([, r]) => r.width > 0 && r.height > 0);
  overlap: for (let i = 0; i < ctrls.length; i++) {  // no control lies over another
    for (let j = i + 1; j < ctrls.length; j++) {
      const [a, r] = ctrls[i], [b, q] = ctrls[j];
      if (a.contains(b) || b.contains(a)) continue;
      if (Math.min(r.right, q.right) - Math.max(r.left, q.left) > 1 && Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top) > 1) {
        out.push(["controls-overlap", name(a) + " (" + box(r) + ") over " + name(b) + " (" + box(q) + ")"]);
        break overlap;
      }
    }
  }
  return out;
})
