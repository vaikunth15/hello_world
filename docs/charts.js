/* Small SVG chart kit. All labels go in via textContent (data is scraped = untrusted). */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const tip = () => document.getElementById("tooltip");

  function s(tag, attrs = {}, parent) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }
  function text(parent, x, y, str, attrs = {}) {
    const t = s("text", { x, y, ...attrs }, parent);
    t.textContent = str;
    return t;
  }

  function showTip(evt, rows) {
    const t = tip();
    t.replaceChildren();
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "trow";
      if (r.color) {
        const k = document.createElement("span");
        k.className = "tkey";
        k.style.setProperty("--c", r.color);
        row.appendChild(k);
      }
      const v = document.createElement("span");
      v.className = "tv";
      v.textContent = r.value;
      const l = document.createElement("span");
      l.className = "tl";
      l.textContent = r.label;
      row.append(v, l);
      t.appendChild(row);
    }
    t.hidden = false;
    let x, y;
    if (evt.clientX !== undefined && evt.type !== "focus") { x = evt.clientX; y = evt.clientY; }
    else { const b = evt.target.getBoundingClientRect(); x = b.right; y = b.top; }
    const w = t.offsetWidth, h = t.offsetHeight;
    t.style.left = Math.min(x + 14, window.innerWidth - w - 8) + "px";
    t.style.top = Math.max(8, y - h - 10) + "px";
  }
  function hideTip() { tip().hidden = true; }

  /* bar path: square at baseline (x0), 4px rounded at the data end */
  function hbarPath(x0, y, w, h, r = 4) {
    r = Math.min(r, w, h / 2);
    if (w <= 0) return "";
    return `M${x0},${y}H${x0 + w - r}Q${x0 + w},${y} ${x0 + w},${y + r}V${y + h - r}Q${x0 + w},${y + h} ${x0 + w - r},${y + h}H${x0}Z`;
  }
  function colPath(x, y0, w, h, r = 4) {
    r = Math.min(r, h, w / 2);
    if (h <= 0) return "";
    return `M${x},${y0}V${y0 - h + r}Q${x},${y0 - h} ${x + r},${y0 - h}H${x + w - r}Q${x + w},${y0 - h} ${x + w},${y0 - h + r}V${y0}Z`;
  }

  function tableFallback(container, headers, rows) {
    const d = document.createElement("details");
    const sm = document.createElement("summary");
    sm.textContent = "View as table";
    const tbl = document.createElement("table");
    tbl.className = "data";
    const tr = tbl.createTHead().insertRow();
    headers.forEach((h, i) => { const th = document.createElement("th"); th.textContent = h; if (i) th.className = "num"; tr.appendChild(th); });
    const tb = tbl.createTBody();
    for (const r of rows) {
      const row = tb.insertRow();
      r.forEach((c, i) => { const td = row.insertCell(); td.textContent = c; if (i) td.className = "num"; });
    }
    d.append(sm, tbl);
    container.appendChild(d);
  }

  function empty(container, msg) {
    const p = document.createElement("div");
    p.className = "chart-empty";
    p.textContent = msg || "Not enough data for the current filters.";
    container.appendChild(p);
  }

  /* Ranked horizontal bars, one hue. rows: [{label, value, display, sub}] */
  function hbar(container, rows, { color = "var(--series-1)", unit = "", fmt = String, labelWidth = 150 } = {}) {
    container.replaceChildren();
    if (!rows.length) return empty(container);
    const width = Math.max(320, container.clientWidth || 440);
    const barH = 16, gap = 10, valW = 74;
    const height = rows.length * (barH + gap);
    const svg = s("svg", { class: "chart", viewBox: `0 0 ${width} ${height}`, height, role: "img" }, container);
    const max = Math.max(...rows.map(r => r.value)) || 1;
    const x0 = labelWidth, plotW = width - labelWidth - valW;
    s("line", { class: "baseline", x1: x0, x2: x0, y1: 0, y2: height - gap }, svg);
    rows.forEach((r, i) => {
      const y = i * (barH + gap);
      const g = s("g", { class: "row", tabindex: 0 }, svg);
      const lbl = text(g, x0 - 8, y + barH / 2 + 4, truncate(r.label, 22), { "text-anchor": "end" });
      if (r.label.length > 22) s("title", {}, lbl).textContent = r.label;
      const w = Math.max(2, (r.value / max) * plotW);
      s("path", { class: "bar", d: hbarPath(x0 + 1, y, w, barH), fill: color }, g);
      text(g, x0 + 1 + w + 6, y + barH / 2 + 4, r.display ?? fmt(r.value), { class: "val" });
      s("rect", { class: "hit", x: 0, y: y - gap / 2, width, height: barH + gap }, g);
      const tipRows = [{ value: r.display ?? fmt(r.value), label: r.label + (unit ? " · " + unit : "") }];
      if (r.sub) tipRows.push({ value: "", label: r.sub });
      const on = e => showTip(e, tipRows);
      g.addEventListener("pointermove", on); g.addEventListener("focus", on);
      g.addEventListener("pointerleave", hideTip); g.addEventListener("blur", hideTip);
    });
  }

  /* Columns with value on each cap (few buckets). rows: [{label, value, display}] */
  function columns(container, rows, { color = "var(--series-1)", fmt = String, unit = "" } = {}) {
    container.replaceChildren();
    if (!rows.some(r => r.value)) return empty(container);
    const width = Math.max(320, container.clientWidth || 440), height = 200;
    const top = 18, bottom = 34;
    const svg = s("svg", { class: "chart", viewBox: `0 0 ${width} ${height}`, height, role: "img" }, container);
    const max = Math.max(...rows.map(r => r.value)) || 1;
    const band = width / rows.length, colW = Math.min(24, band * 0.6);
    const y0 = height - bottom, plotH = y0 - top;
    s("line", { class: "baseline", x1: 0, x2: width, y1: y0 + 0.5, y2: y0 + 0.5 }, svg);
    rows.forEach((r, i) => {
      const cx = band * i + band / 2;
      const g = s("g", { class: "row", tabindex: 0 }, svg);
      const h = r.value ? Math.max(2, (r.value / max) * plotH) : 0;
      if (h) s("path", { class: "bar", d: colPath(cx - colW / 2, y0, colW, h), fill: color }, g);
      if (r.value) text(g, cx, y0 - h - 6, r.display ?? fmt(r.value), { class: "val", "text-anchor": "middle" });
      text(g, cx, y0 + 16, r.label, { class: "tick", "text-anchor": "middle" });
      s("rect", { class: "hit", x: band * i, y: top - 10, width: band, height: plotH + bottom }, g);
      const on = e => showTip(e, [{ value: r.display ?? fmt(r.value), label: r.label + (unit ? " · " + unit : "") }]);
      g.addEventListener("pointermove", on); g.addEventListener("focus", on);
      g.addEventListener("pointerleave", hideTip); g.addEventListener("blur", hideTip);
    });
  }

  /* Multi-line over time with crosshair. series: [{name, color, values:[number]}], xs: [label] */
  function lines(container, xs, series, { fmt = String } = {}) {
    container.replaceChildren();
    if (!xs.length) return empty(container, "The trend builds up as weekly runs accumulate.");
    const leg = document.createElement("div");
    leg.className = "chart-legend";
    for (const sr of series) {
      const it = document.createElement("span");
      const k = document.createElement("span");
      k.className = "key line"; k.style.setProperty("--c", sr.color);
      it.append(k, document.createTextNode(sr.name));
      leg.appendChild(it);
    }
    container.appendChild(leg);
    const width = Math.max(320, container.clientWidth || 440), height = 200;
    const left = 44, right = 90, top = 10, bottom = 26;
    const svg = s("svg", { class: "chart", viewBox: `0 0 ${width} ${height}`, height, role: "img" }, container);
    const all = series.flatMap(sr => sr.values).filter(v => v != null);
    const max = niceMax(Math.max(1, ...all));
    const plotW = width - left - right, plotH = height - top - bottom;
    const X = i => left + (xs.length === 1 ? plotW / 2 : (i / (xs.length - 1)) * plotW);
    const Y = v => top + plotH - (v / max) * plotH;
    for (let k = 0; k <= 4; k++) {
      const v = (max / 4) * k, y = Y(v);
      s("line", { class: k ? "gridline" : "baseline", x1: left, x2: width - right, y1: y, y2: y }, svg);
      text(svg, left - 6, y + 4, fmt(v), { class: "tick", "text-anchor": "end" });
    }
    const step = Math.ceil(xs.length / 6);
    xs.forEach((x, i) => { if (i % step === 0 || i === xs.length - 1) text(svg, X(i), height - 6, x, { class: "tick", "text-anchor": "middle" }); });
    for (const sr of series) {
      const pts = sr.values.map((v, i) => [X(i), Y(v || 0)]);
      if (pts.length > 1) s("path", { d: "M" + pts.map(p => p.join(",")).join("L"), fill: "none", stroke: sr.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      const last = pts[pts.length - 1];
      s("circle", { cx: last[0], cy: last[1], r: 4, fill: sr.color, stroke: "var(--surface-1)", "stroke-width": 2 }, svg);
      text(svg, last[0] + 8, last[1] + 4, `${sr.name} ${fmt(sr.values[sr.values.length - 1] || 0)}`, { class: "val" });
    }
    const cross = s("line", { class: "crosshair", y1: top, y2: top + plotH, visibility: "hidden" }, svg);
    const hit = s("rect", { class: "hit", x: left, y: top, width: plotW, height: plotH }, svg);
    hit.addEventListener("pointermove", e => {
      const b = svg.getBoundingClientRect();
      const px = (e.clientX - b.left) * (width / b.width);
      const i = xs.length === 1 ? 0 : Math.max(0, Math.min(xs.length - 1, Math.round(((px - left) / plotW) * (xs.length - 1))));
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
      showTip(e, [{ value: xs[i], label: "" }, ...series.map(sr => ({ value: fmt(sr.values[i] || 0), label: sr.name, color: sr.color }))]);
    });
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  }

  function niceMax(v) {
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }
  function truncate(str, n) { return str.length > n ? str.slice(0, n - 1) + "…" : str; }

  window.Charts = { hbar, columns, lines, tableFallback, showTip, hideTip };
})();
