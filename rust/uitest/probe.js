// Injected by rust/uitest/run.py after each page load (Runtime.evaluate: the
// page's CSP doesn't apply to it). Read-only helpers for the UI checks;
// window.__ui is the harness's, the page never sees it before it is loaded.
(() => {
  if (window.__ui) return;
  const norm = (s) => (s || "").replace(/[   ]/g, " ").replace(/\s+/g, " ").trim();
  const all = (hook) => [...document.querySelectorAll(`[data-test="${hook}"]`)];
  // The shown text: like textContent, but without display:none parts and with a
  // space around block-level children (table cells, flex/grid items, divs).
  function textOf(root) {
    let out = "";
    (function walk(n) {
      if (n.nodeType === Node.TEXT_NODE) { out += n.nodeValue; return; }
      if (n.nodeType !== Node.ELEMENT_NODE || ["SCRIPT", "STYLE", "TEMPLATE"].includes(n.tagName)) return;
      const d = getComputedStyle(n).display;
      if (d === "none") return;
      const block = n !== root && d !== "inline" && d !== "contents";
      if (block) out += " ";
      for (const c of n.childNodes) walk(c);
      if (block) out += " ";
    })(root);
    return norm(out);
  }

  // rendered: not display:none / visibility:hidden / opacity:0 / in a closed <details>
  const rendered = (el) => !!el && el.isConnected && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  function visible(el) {
    if (!rendered(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  function describe(el) {
    const r = el.getBoundingClientRect();
    const attrs = {};
    for (const a of el.attributes) attrs[a.name] = a.value;
    return {
      text: textOf(el), visible: visible(el), rendered: rendered(el), tag: el.tagName.toLowerCase(),
      attrs, value: typeof el.value === "string" ? el.value : null, open: el.tagName === "DETAILS" ? el.open : null,
      rect: { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom },
      fontSize: parseFloat(getComputedStyle(el).fontSize),
      links: [...el.querySelectorAll("a[href]")].map((a) => a.href),
      name: norm(el.getAttribute("aria-label") || el.textContent || el.getAttribute("title")),
    };
  }
  const info = (hook) => all(hook).map(describe);

  // --- colours: any CSS colour syntax, resolved by a 1x1 canvas to sRGB ---
  const ctx = (() => {
    const c = document.createElement("canvas");
    c.width = c.height = 1;
    return c.getContext("2d", { willReadFrequently: true });
  })();
  function rgba(css) {
    if (!css || css === "none" || css.startsWith("url(")) return null;
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "rgba(0, 0, 0, 0)";
    ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  }
  const mix = (top, bottom) => [0, 1, 2].map((i) => top[i] * top[3] + bottom[i] * (1 - top[3]));
  // Effective background behind an element: its own and its ancestors' colours,
  // composited. null when a background image (gradient) is in the way.
  function background(el) {
    const layers = [];
    let opaque = false;
    for (let n = el; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage !== "none") return { rgb: null, opaque: false };
      const c = rgba(cs.backgroundColor);
      if (c && c[3] > 0) {
        layers.push(c);
        if (c[3] >= 0.999) { opaque = true; break; }
      }
    }
    let out = [255, 255, 255];
    for (let i = layers.length - 1; i >= 0; i--) out = mix(layers[i], out);
    return { rgb: out, opaque };
  }
  function lum(rgb) {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2]);
  }
  function ratio(a, b) {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  }
  const hex = (rgb) => "#" + rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

  // WCAG AA for every visible text: 4.5:1, or 3:1 from 24 px (18.66 px bold).
  function contrast() {
    const bad = [];
    let checked = 0, skipped = 0;
    const seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const el = t.parentElement;
      if (!el || seen.has(el) || !t.nodeValue.trim()) continue;
      seen.add(el);
      if (el.closest("script, style, title, noscript, option, [disabled], [aria-disabled='true']")) continue;
      if (!visible(el)) continue;
      const cs = getComputedStyle(el);
      const fg = rgba(el instanceof SVGElement ? cs.fill : cs.color);
      const bg = background(el);
      if (!fg || !bg.rgb) { skipped++; continue; }
      let opacity = 1;
      for (let n = el; n; n = n.parentElement) opacity *= parseFloat(getComputedStyle(n).opacity);
      const text = mix([...mix(fg, bg.rgb), opacity], bg.rgb);
      const size = parseFloat(cs.fontSize);
      const need = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight, 10) >= 700) ? 3 : 4.5;
      const r = ratio(text, bg.rgb);
      checked++;
      if (r + 1e-6 < need) {
        const hook = el.closest("[data-test]");
        bad.push(`"${norm(t.nodeValue).slice(0, 40)}" (${el.tagName.toLowerCase()}${hook ? ` in [data-test=${hook.dataset.test}]` : ""}): `
          + `${r.toFixed(2)}:1 < ${need}:1, text ${hex(text)} on ${hex(bg.rgb)}`);
      }
    }
    return { checked, skipped, bad };
  }

  function page() {
    const bg = background(document.body);
    return {
      lang: document.documentElement.lang, title: document.title,
      sw: document.documentElement.scrollWidth, sh: document.documentElement.scrollHeight,
      // clientWidth, not innerWidth: with mobile emulation the layout viewport grows to fit wide content
      iw: document.documentElement.clientWidth, ih: document.documentElement.clientHeight,
      bodyBg: bg.rgb && hex(bg.rgb), bodyLum: bg.rgb && lum(bg.rgb), bodyBgOpaque: bg.opaque,
    };
  }

  // Elements that stick out on the right (for the overflow message).
  function overflowing() {
    const out = [];
    for (const el of document.body.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (r.right > document.documentElement.clientWidth + 1 && visible(el)) {
        const hook = el.closest("[data-test]");
        out.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.trim().replace(/\s+/g, ".") : ""}`
          + `${hook ? ` in [data-test=${hook.dataset.test}]` : ""} right=${Math.round(r.right)}`);
      }
    }
    return out.slice(-6);
  }

  // Visible controls smaller than 24x24 px or without an accessible name.
  function controls() {
    const out = [];
    for (const el of document.querySelectorAll("button, summary, [role='button'], input[type='button']")) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      const name = norm(el.getAttribute("aria-label") || el.textContent || el.getAttribute("title"));
      const what = `${el.tagName.toLowerCase()}${el.dataset.test ? `[data-test=${el.dataset.test}]` : ""} "${name.slice(0, 30)}"`;
      if (r.width < 24 || r.height < 24) out.push(`${what}: ${Math.round(r.width)}x${Math.round(r.height)} px (minimum 24x24)`);
      if (!name) out.push(`${what}: no accessible name (text or aria-label)`);
    }
    return out;
  }

  const animations = () => document.getAnimations().filter((a) => a.playState === "running")
    .map((a) => a.animationName || a.transitionProperty || a.constructor.name);

  function openDetails() {
    for (const d of document.querySelectorAll("details")) d.open = true;
  }

  window.__ui = { info, contrast, page, overflowing, controls, animations, openDetails };
})();
