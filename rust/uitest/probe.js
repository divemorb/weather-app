// Injected by rust/uitest/run.py after each page load (Runtime.evaluate: the page's CSP doesn't apply to it); read-only helpers for the UI checks, window.__ui is the harness's, the page never sees it.
(() => {
  if (window.__ui) return;
  const norm = (s) => (s || "").replace(/[   ]/g, " ").replace(/\s+/g, " ").trim();
  const all = (hook) => [...document.querySelectorAll(`[data-test="${hook}"]`)];
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

  const icons = (hook) => all(hook).flatMap((b) => [...b.querySelectorAll("svg")].filter(visible)
    .map((s) => s.getAttribute("class") || s.innerHTML.slice(0, 60)));

  function textColor(hook) {
    const el = all(hook)[0];
    const c = el && rgba(getComputedStyle(el).color);
    if (!c) return null;
    const [r, g, b] = c.slice(0, 3).map((v) => v / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
    const sat = max === min ? 0 : (max - min) / (1 - Math.abs(2 * l - 1));
    return { hex: hex(c.slice(0, 3)), sat };
  }

  // Where a hook's text is cut off: the element or ancestor that clips (overflow not visible, content larger than its box); [] when all of it shows.
  function clipped(hook) {
    const out = [];
    for (const el of all(hook)) {
      for (let n = el; n && n !== document.body; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
        if (n.scrollWidth > n.clientWidth + 1 || n.scrollHeight > n.clientHeight + 1) {
          out.push(`${n.tagName.toLowerCase()}.${[...n.classList].join(".")} clips it: content ` +
            `${n.scrollWidth}x${n.scrollHeight} px in a ${n.clientWidth}x${n.clientHeight} px box ` +
            `(overflow ${cs.overflowX}/${cs.overflowY}, text-overflow ${cs.textOverflow})`);
          break;
        }
      }
    }
    return out;
  }

  // Visible elements inside a hook that reach past its content box on the right (into its padding or beyond it); a scroll container inside the hook doesn't count.
  function sticksOut(hook) {
    const out = [];
    for (const root of all(hook)) {
      if (!visible(root)) continue;
      const cs = getComputedStyle(root);
      const edge = root.getBoundingClientRect().right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight);
      for (const el of root.querySelectorAll("*")) {
        if (!visible(el)) continue;
        let right = el.getBoundingClientRect().right;
        for (let n = el.parentElement; n && n !== root; n = n.parentElement) {
          if (getComputedStyle(n).overflowX !== "visible") right = Math.min(right, n.getBoundingClientRect().right);
        }
        if (right > edge + 1) {
          out.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.trim().replace(/\s+/g, ".") : ""}`
            + ` ends at ${Math.round(right)} px, past the content edge of [data-test=${hook}] at ${Math.round(edge)} px`);
        }
      }
    }
    return out.slice(0, 6);
  }

  function summaryGaps(hook) {
    const d = all(hook)[0];
    const sum = d && d.querySelector(":scope > summary");
    if (!sum) return null;
    const a = d.getBoundingClientRect(), b = sum.getBoundingClientRect();
    return { above: b.top - a.top, below: a.bottom - b.bottom };
  }

  function tiles() {
    const main = document.getElementById("dashboard");
    if (!main) return null;
    const cs = getComputedStyle(main);
    const grid = cs.display === "grid" || cs.display === "inline-grid";
    const tracks = grid ? cs.gridTemplateColumns.split(/\s+/).filter((t) => /px$/.test(t)).map(parseFloat) : [];
    const r = main.getBoundingClientRect();
    const list = [...main.children].filter(visible).map((el) => {
      const b = el.getBoundingClientRect();
      return { id: el.id || el.tagName.toLowerCase(), x: b.x, y: b.y, w: b.width, h: b.height, right: b.right, bottom: b.bottom };
    });
    return { grid, columns: grid ? tracks.length : 1, tracks, x: r.x, w: r.width, right: r.right, list };
  }

  function sky() {
    const els = all("sky");
    const scene = document.documentElement.getAttribute("data-scene");
    if (els.length !== 1) return { count: els.length, scene };
    const el = els[0], cs = getComputedStyle(el), r = el.getBoundingClientRect();
    const covered = [];
    const t = tiles();
    for (const tile of t ? t.list : []) {
      const hit = document.elementFromPoint(tile.x + tile.w / 2, tile.y + Math.min(tile.h / 2, 40));
      if (hit && (el === hit || el.contains(hit))) covered.push(tile.id);
    }
    return { count: 1, scene, position: cs.position, ariaHidden: el.getAttribute("aria-hidden"),
      pointerEvents: cs.pointerEvents, rect: { x: r.x, y: r.y, w: r.width, h: r.height },
      vw: document.documentElement.clientWidth, vh: document.documentElement.clientHeight, covered };
  }

  function onlySky(on) {
    const el = all("sky")[0];
    for (const n of document.body.querySelectorAll("*")) {
      if (el && (el === n || el.contains(n) || n.contains(el))) continue;
      if (on) n.style.setProperty("visibility", "hidden", "important");
      else n.style.removeProperty("visibility");
    }
    return !!el;
  }

  // Make all text transparent (its line boxes and everything behind them stay) so a screenshot shows what each text is drawn on; through the CSSOM, which the page's CSP allows (a <style> element it doesn't); the old values are put back afterwards.
  let hidden = [];
  function hideText(on) {
    if (!on) {
      const restore = ([el, prop, value, prio]) => {
        if (value) el.style.setProperty(prop, value, prio);
        else el.style.removeProperty(prop);
      };
      hidden.filter((h) => h[1] !== "transition").forEach(restore);
      for (const [el] of hidden) getComputedStyle(el).color;
      hidden.filter((h) => h[1] === "transition").forEach(restore);
      hidden = [];
      return;
    }
    const set = (el, prop, value) => {
      hidden.push([el, prop, el.style.getPropertyValue(prop), el.style.getPropertyPriority(prop)]);
      el.style.setProperty(prop, value, "important");
    };
    for (const el of document.body.querySelectorAll("*")) {
      if (el.closest("[data-test=sky]")) continue;
      set(el, "transition", "none");
      set(el, "color", "transparent");
      set(el, "-webkit-text-fill-color", "transparent");
      set(el, "text-shadow", "none");
      if (el instanceof SVGTextContentElement) {
        set(el, "fill", "transparent");
        set(el, "stroke", "transparent");
      }
    }
  }

  function textItems() {
    const items = [];
    const seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const el = t.parentElement;
      if (!el || !t.nodeValue.trim()) continue;
      if (el.closest("script, style, title, noscript, option, [disabled], [aria-disabled='true'], [data-test=sky]")) continue;
      if (!visible(el)) continue;
      const cs = getComputedStyle(el);
      const fg = rgba(el instanceof SVGElement ? cs.fill : cs.color);
      if (!fg) continue;
      let opacity = 1;
      for (let n = el; n; n = n.parentElement) opacity *= parseFloat(getComputedStyle(n).opacity);
      const size = parseFloat(cs.fontSize);
      const need = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight, 10) >= 700) ? 3 : 4.5;
      const range = document.createRange();
      range.selectNodeContents(t);
      const rects = [...range.getClientRects()].filter((b) => b.width >= 1 && b.height >= 1)
        .map((b) => ({ x: b.x, y: b.y, w: b.width, h: b.height }));
      if (!rects.length) continue;
      const key = el.closest("[data-test]");
      const label = `"${norm(t.nodeValue).slice(0, 40)}" (${el.tagName.toLowerCase()}${key ? ` in [data-test=${key.dataset.test}]` : ""})`;
      if (seen.has(label)) continue;
      seen.add(label);
      items.push({ label, fg, opacity, need, rects });
    }
    return items;
  }

  async function decode(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const bmp = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
    const c = new OffscreenCanvas(bmp.width, bmp.height);
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(bmp, 0, 0);
    return g.getImageData(0, 0, bmp.width, bmp.height);
  }

  async function pixelContrast(b64, items, dy, pct) {
    const img = await decode(b64);
    const out = [];
    for (const it of items) {
      const ratios = [];
      let worstBg = null, worst = Infinity;
      for (const r of it.rects) {
        const x0 = Math.max(0, Math.floor(r.x)), x1 = Math.min(img.width, Math.ceil(r.x + r.w));
        const y0 = Math.max(0, Math.floor(r.y - dy)), y1 = Math.min(img.height, Math.ceil(r.y - dy + r.h));
        for (let y = y0; y < y1; y++) {
          for (let x = x0; x < x1; x++) {
            const i = (y * img.width + x) * 4;
            const bg = [img.data[i], img.data[i + 1], img.data[i + 2]];
            const text = mix([...mix(it.fg, bg), it.opacity], bg);
            const q = ratio(text, bg);
            ratios.push(q);
            if (q < worst) { worst = q; worstBg = bg; }
          }
        }
      }
      if (!ratios.length) continue;
      ratios.sort((a, b) => a - b);
      const at = ratios[Math.min(ratios.length - 1, Math.floor(ratios.length * pct))];
      out.push({ label: it.label, need: it.need, ratio: at, fg: hex(it.fg.slice(0, 3)), bg: hex(worstBg) });
    }
    return out;
  }

  async function diff(a, b) {
    const [p, q] = await Promise.all([decode(a), decode(b)]);
    if (p.width !== q.width || p.height !== q.height) return 1;
    let n = 0;
    for (let i = 0; i < p.data.length; i += 4) {
      if (p.data[i] !== q.data[i] || p.data[i + 1] !== q.data[i + 1] || p.data[i + 2] !== q.data[i + 2]) n++;
    }
    return n / (p.width * p.height);
  }

  async function diffIn(a, b, rects, delta) {
    const [p, q] = await Promise.all([decode(a), decode(b)]);
    if (p.width !== q.width || p.height !== q.height) return null;
    const inRect = (x, y) => rects.some((r) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h);
    let inN = 0, inC = 0, outN = 0, outC = 0;
    for (let y = 0; y < p.height; y++) {
      for (let x = 0; x < p.width; x++) {
        const i = (y * p.width + x) * 4;
        const changed = Math.max(Math.abs(p.data[i] - q.data[i]), Math.abs(p.data[i + 1] - q.data[i + 1]),
          Math.abs(p.data[i + 2] - q.data[i + 2])) >= delta;
        if (inRect(x, y)) { inN++; if (changed) inC++; } else { outN++; if (changed) outC++; }
      }
    }
    return { inside: inN ? inC / inN : 0, outside: outN ? outC / outN : 0 };
  }

  async function medianIn(b64, rects) {
    const img = await decode(b64);
    return rects.map((r) => {
      const ch = [[], [], []];
      const x0 = Math.max(0, Math.floor(r.x)), x1 = Math.min(img.width, Math.ceil(r.x + r.w));
      const y0 = Math.max(0, Math.floor(r.y)), y1 = Math.min(img.height, Math.ceil(r.y + r.h));
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const i = (y * img.width + x) * 4;
          for (let k = 0; k < 3; k++) ch[k].push(img.data[i + k]);
        }
      }
      if (!ch[0].length) return null;
      return ch.map((v) => v.sort((a, b) => a - b)[v.length >> 1]);
    });
  }

  // Pause every animation and seek it to phase (0..1) of its own cycle: currentTime = delay + (phase + n) * duration, n the smallest >= 0 that keeps it >= 0 (CSS uses negative delays); skips non-finite durations; leaves them paused.
  function seekCycle(phase) {
    for (const a of document.getAnimations()) {
      const e = a.effect;
      if (!e || !e.getComputedTiming) continue;
      const t = e.getComputedTiming();
      if (!Number.isFinite(t.duration) || !(t.duration > 0)) continue;
      a.pause();
      let n = 0;
      while (t.delay + (phase + n) * t.duration < 0) n++;
      a.currentTime = t.delay + (phase + n) * t.duration;
    }
  }

  // Pause every animation and seek it to the given absolute time in milliseconds (the glass check: two frames GLASS_GAP_S apart without waiting); leaves them paused.
  function seekTime(ms) {
    for (const a of document.getAnimations()) {
      a.pause();
      a.currentTime = ms;
    }
  }

  window.__ui = { info, page, overflowing, controls, animations, openDetails, icons, textColor, clipped,
    sticksOut, summaryGaps, tiles, sky, onlySky, hideText, textItems, pixelContrast, diff, diffIn,
    medianIn, seekCycle, seekTime };
})();
