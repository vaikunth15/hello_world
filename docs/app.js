/* Coimbatore Property Index - dashboard. Vanilla JS; all scraped text goes through textContent. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const DATA = new URLSearchParams(location.search).get("data") || "data";

  const TYPE_LABEL = {
    apartment: "Apartment / flat", independent_house: "Independent house", villa: "Villa",
    plot: "Residential plot", pg_hostel: "PG / hostel", farm_house: "Farm house",
    agricultural_land: "Agricultural land", commercial_office: "Office space",
    commercial_shop: "Shop / showroom", commercial_land: "Commercial land",
    warehouse: "Warehouse / godown", industrial: "Industrial", other: "Other",
  };
  const CATEGORY = {
    residential: ["apartment", "independent_house", "villa", "plot", "pg_hostel"],
    commercial: ["commercial_office", "commercial_shop", "commercial_land"],
    "industrial & warehouse": ["warehouse", "industrial"],
    agricultural: ["agricultural_land", "farm_house"],
    other: ["other"],
  };
  const LAND = new Set(["plot", "agricultural_land", "commercial_land"]);
  const BUILT = new Set(["apartment", "independent_house", "villa"]);
  const LABELS = {
    posted_by: { owner: "Owner", agent: "Agent", builder: "Builder" },
    furnishing: { furnished: "Furnished", semi_furnished: "Semi-furnished", unfurnished: "Unfurnished" },
    construction_status: { ready: "Ready to move", under_construction: "Under construction", new_launch: "New launch" },
  };
  const PRICE_PRESETS = {
    sale: [0, 10e5, 20e5, 30e5, 50e5, 75e5, 1e7, 1.5e7, 2e7, 3e7, 5e7, 10e7],
    rent: [0, 5e3, 10e3, 15e3, 20e3, 30e3, 50e3, 1e5, 2e5],
  };
  const SQFT_PER_CENT = 435.6;

  let ALL = [], PROJECTS = [], META = {};
  let FILTERED = [];
  const state = defaults();
  let view = "map";
  let sort = { key: "first_seen_at", dir: -1 }, page = 0;

  function defaults() {
    return { q: "", deal: "", types: [], locs: [], bhk: [], pmin: 0, pmax: 0, amin: 0, amax: 0,
             posted_by: [], furnishing: [], construction_status: [], src: [], appr: [],
             newOnly: false, dropOnly: false, exactOnly: false };
  }

  /* ------------------------------------------------------------ formatting */
  const inr = (v, rent) => {
    if (v == null) return "Price on request";
    let s;
    if (v >= 1e7) s = trim(v / 1e7) + " Cr";
    else if (v >= 1e5) s = trim(v / 1e5) + " L";
    else if (v >= 1e3) s = trim(v / 1e3) + "K";
    else s = String(Math.round(v));
    return "₹" + s + (rent ? "/mo" : "");
  };
  const trim = n => (n >= 100 ? Math.round(n) : Number(n.toFixed(n >= 10 ? 1 : 2))).toString();
  const num = v => v == null ? "–" : Math.round(v).toLocaleString("en-IN");
  const isRent = l => l.transaction_type === "rent" || l.transaction_type === "lease";
  const priceText = l => {
    let s = inr(l.price_inr, isRent(l));
    if (l.price_max_inr) s += " – " + inr(l.price_max_inr, isRent(l)).replace("₹", "");
    return s;
  };
  const areaSqft = l => l.built_up_sqft || l.carpet_sqft || l.plot_sqft;
  const areaText = l => {
    const a = areaSqft(l);
    if (!a) return "–";
    const u = l.area_unit_original;
    if (u && !["sqft"].includes(u) && l.area_value_original) {
      const uname = { cent: "cent", acre: "acre", ground: "ground", sqyd: "sq yd", sqm: "sq m", hectare: "ha", guntha: "guntha" }[u] || u;
      const plural = l.area_value_original !== 1 && ["cent", "acre", "ground", "guntha"].includes(u) ? "s" : "";
      return `${trim(l.area_value_original)} ${uname}${plural} (${num(a)} sq ft)`;
    }
    return num(a) + " sq ft";
  };
  const dateText = iso => iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "–";
  const safeUrl = u => (typeof u === "string" && /^https?:\/\//i.test(u)) ? u : null;
  const median = arr => {
    if (!arr.length) return null;
    const a = [...arr].sort((x, y) => x - y), m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  };
  const cssVar = name => getComputedStyle(document.querySelector(".viz-root")).getPropertyValue(name).trim();
  const colorFor = l => isRent(l) ? cssVar("--series-2") : cssVar("--series-1");

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
    return el;
  }

  /* ------------------------------------------------------------ load */
  async function load() {
    const get = async f => { try { const r = await fetch(`${DATA}/${f}`, { cache: "no-cache" }); return r.ok ? r.json() : null; } catch { return null; } };
    const [meta, listings, projects] = await Promise.all([get("meta.json"), get("listings.json"), get("projects.json")]);
    META = meta || {};
    ALL = (listings || []).filter(l => l && l.id);
    PROJECTS = projects || [];
    ALL.forEach(l => {
      l._search = [l.title, l.locality, l.locality_raw, l.project_name, l.builder, l.advertiser, l.rera_id, l.pincode]
        .filter(Boolean).join(" ").toLowerCase();
    });
    $("refreshed").textContent = META.generated_at
      ? `${ALL.length.toLocaleString("en-IN")} active listings · refreshed ${dateText(META.generated_at)} · updates weekly`
      : "No refresh has run yet";
  }

  /* ------------------------------------------------------------ filters */
  function matches(l, except) {
    const s = state;
    if (s.q) { for (const w of s.q.toLowerCase().split(/\s+/)) if (w && !l._search.includes(w)) return false; }
    if (s.deal === "sale" && l.transaction_type !== "sale") return false;
    if (s.deal === "rent" && !isRent(l)) return false;
    if (except !== "types" && s.types.length && !s.types.includes(l.property_type)) return false;
    if (except !== "locs" && s.locs.length && !s.locs.includes(l.locality || "(unmapped)")) return false;
    if (s.bhk.length) {
      const b = l.bhk ? Math.min(5, Math.floor(l.bhk)) : null;
      if (!s.bhk.includes(String(b))) return false;
    }
    if (s.deal && (s.pmin || s.pmax)) {
      if (l.price_inr == null) return false;
      if (s.pmin && l.price_inr < s.pmin) return false;
      if (s.pmax && l.price_inr > s.pmax) return false;
    }
    const a = areaSqft(l);
    if (s.amin && !(a >= s.amin)) return false;
    if (s.amax && !(a <= s.amax)) return false;
    for (const k of ["posted_by", "furnishing", "construction_status"]) if (s[k].length && !s[k].includes(l[k])) return false;
    if (except !== "src" && s.src.length && !s.src.includes(l.source_id)) return false;
    if (s.appr.length && !s.appr.every(x => (l.approvals || []).includes(x))) return false;
    if (s.newOnly && !l.is_new) return false;
    if (s.dropOnly && !l.previous_price_inr) return false;
    if (s.exactOnly && l.geo_precision !== "exact") return false;
    return true;
  }

  function checklist(container, items, key, { counts } = {}) {
    container.replaceChildren();
    for (const it of items) {
      const cb = h("input", { type: "checkbox", value: it.value });
      cb.checked = state[key].includes(it.value);
      cb.addEventListener("change", () => {
        state[key] = cb.checked ? [...state[key], it.value] : state[key].filter(v => v !== it.value);
        update();
      });
      container.append(h("label", { class: "check" }, cb, it.label, counts ? h("span", { class: "n" }, num(counts[it.value] || 0)) : null));
    }
  }

  function buildFilterControls() {
    // types grouped by category, with counts ignoring the type filter itself
    const tc = {};
    ALL.forEach(l => { if (matches(l, "types")) tc[l.property_type] = (tc[l.property_type] || 0) + 1; });
    const typePanel = $("f-type");
    typePanel.replaceChildren();
    for (const [cat, types] of Object.entries(CATEGORY)) {
      const present = types.filter(t => ALL.some(l => l.property_type === t));
      if (!present.length) continue;
      typePanel.append(h("h4", {}, cat));
      const box = h("div", { style: "display:grid;gap:4px" });
      checklist(box, present.map(t => ({ value: t, label: TYPE_LABEL[t] })), "types", { counts: tc });
      typePanel.append(box);
    }
    if (!typePanel.childElementCount) typePanel.append(h("span", { class: "muted" }, "No listings yet"));
    renderLocalityList();

    // more filters
    const more = $("f-more");
    more.replaceChildren();
    const group = (title, key, map) => {
      const vals = Object.keys(map).filter(v => ALL.some(l => l[key] === v));
      if (!vals.length) return;
      more.append(h("h4", {}, title));
      const box = h("div", { style: "display:grid;gap:4px" });
      checklist(box, vals.map(v => ({ value: v, label: map[v] })), key);
      more.append(box);
    };
    group("Posted by", "posted_by", LABELS.posted_by);
    group("Furnishing", "furnishing", LABELS.furnishing);
    group("Construction", "construction_status", LABELS.construction_status);
    const srcs = {};
    ALL.forEach(l => { srcs[l.source_id] = l.source_name || l.source_id; });
    if (Object.keys(srcs).length) {
      more.append(h("h4", {}, "Source"));
      const box = h("div", { style: "display:grid;gap:4px" });
      checklist(box, Object.entries(srcs).map(([v, label]) => ({ value: v, label })), "src");
      more.append(box);
    }
    more.append(h("h4", {}, "Approvals & flags"));
    const box = h("div", { style: "display:grid;gap:4px" });
    checklist(box, ["DTCP", "RERA", "LPA"].map(v => ({ value: v, label: `${v} mentioned` })), "appr");
    more.append(box);
    for (const [key, label] of [["newOnly", "New this week"], ["dropOnly", "Price dropped"], ["exactOnly", "Exact map position only"]]) {
      const cb = h("input", { type: "checkbox" });
      cb.checked = state[key];
      cb.addEventListener("change", () => { state[key] = cb.checked; update(); });
      more.append(h("label", { class: "check" }, cb, label));
    }
  }

  function renderLocalityList() {
    const q = $("f-loc-q").value.toLowerCase();
    const lc = {};
    ALL.forEach(l => { if (matches(l, "locs")) { const k = l.locality || "(unmapped)"; lc[k] = (lc[k] || 0) + 1; } });
    const names = [...new Set(ALL.map(l => l.locality || "(unmapped)"))]
      .filter(n => !q || n.toLowerCase().includes(q))
      .sort((a, b) => (lc[b] || 0) - (lc[a] || 0) || a.localeCompare(b));
    checklist($("f-loc"), names.map(n => ({ value: n, label: n })), "locs", { counts: lc });
  }

  function syncControls() {
    $("f-q").value = state.q;
    $("f-deal").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === state.deal)));
    $("f-bhk").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(state.bhk.includes(b.dataset.v))));
    const presets = PRICE_PRESETS[state.deal || "sale"];
    for (const [id, key, label] of [["f-pmin", "pmin", "No min"], ["f-pmax", "pmax", "No max"]]) {
      const sel = $(id);
      sel.replaceChildren(...presets.map(v => h("option", { value: v }, v ? inr(v, state.deal === "rent") : label)));
      sel.value = String(state[key]);
      if (sel.value !== String(state[key])) { state[key] = 0; sel.value = "0"; }
      sel.disabled = !state.deal;
      sel.title = state.deal ? "" : "Choose Buy or Rent to set a budget";
    }
    $("f-amin").value = state.amin || "";
    $("f-amax").value = state.amax || "";
    const mark = (id, on, label) => { const s = $(id).querySelector("summary"); s.classList.toggle("active", on); s.textContent = label; };
    mark("dd-type", state.types.length > 0, state.types.length ? `Type (${state.types.length})` : "Property type");
    mark("dd-loc", state.locs.length > 0, state.locs.length === 1 ? state.locs[0] : state.locs.length ? `Localities (${state.locs.length})` : "Locality");
    const budgetOn = (state.deal && (state.pmin || state.pmax)) || state.amin || state.amax;
    mark("dd-price", !!budgetOn, budgetOn ? "Budget / area ✓" : "Budget");
    const moreN = ["posted_by", "furnishing", "construction_status", "src", "appr"].reduce((n, k) => n + state[k].length, 0)
      + ["newOnly", "dropOnly", "exactOnly"].filter(k => state[k]).length;
    mark("dd-more", moreN > 0, moreN ? `More (${moreN})` : "More");
  }

  function wireFilters() {
    let t;
    $("f-q").addEventListener("input", e => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); update(); }, 200); });
    $("f-deal").addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      state.deal = b.dataset.v; state.pmin = state.pmax = 0; update();
    });
    $("f-bhk").addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      const v = b.dataset.v;
      state.bhk = state.bhk.includes(v) ? state.bhk.filter(x => x !== v) : [...state.bhk, v];
      update();
    });
    $("f-pmin").addEventListener("change", e => { state.pmin = +e.target.value; update(); });
    $("f-pmax").addEventListener("change", e => { state.pmax = +e.target.value; update(); });
    $("f-amin").addEventListener("change", e => { state.amin = +e.target.value || 0; update(); });
    $("f-amax").addEventListener("change", e => { state.amax = +e.target.value || 0; update(); });
    $("f-loc-q").addEventListener("input", renderLocalityList);
    $("f-reset").addEventListener("click", () => { Object.assign(state, defaults()); update(); });
    $("export").addEventListener("click", exportCsv);
    // close dropdowns when clicking elsewhere
    document.addEventListener("click", e => {
      document.querySelectorAll("details.dd[open]").forEach(d => { if (!d.contains(e.target)) d.open = false; });
    });
  }

  /* ------------------------------------------------------------ url state */
  function writeHash() {
    const p = new URLSearchParams();
    const d = defaults();
    for (const [k, v] of Object.entries(state)) {
      if (JSON.stringify(v) === JSON.stringify(d[k])) continue;
      p.set(k, Array.isArray(v) ? v.join("|") : String(v));
    }
    if (view !== "map") p.set("view", view);
    const s = p.toString();
    try { history.replaceState(null, "", s ? "#" + s : location.pathname + location.search); } catch { /* sandboxed host */ }
  }
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const d = defaults();
    for (const [k, v] of p) {
      if (k === "view") { view = v; continue; }
      if (!(k in d)) continue;
      if (Array.isArray(d[k])) state[k] = v ? v.split("|") : [];
      else if (typeof d[k] === "boolean") state[k] = v === "true";
      else if (typeof d[k] === "number") state[k] = +v || 0;
      else state[k] = v;
    }
  }

  /* ------------------------------------------------------------ KPIs */
  function renderKpis() {
    const F = FILTERED;
    const sale = F.filter(l => l.transaction_type === "sale"), rent = F.filter(isRent);
    const ppsf = median(sale.filter(l => l.price_per_sqft && BUILT.has(l.property_type)).map(l => l.price_per_sqft));
    const perCent = median(sale.filter(l => l.property_type === "plot" && l.price_inr && l.plot_sqft)
      .map(l => l.price_inr / (l.plot_sqft / SQFT_PER_CENT)));
    const mrent = median(rent.filter(l => l.price_inr && BUILT.has(l.property_type)).map(l => l.price_inr));
    const newN = F.filter(l => l.is_new).length, drops = F.filter(l => l.previous_price_inr).length;
    const srcs = (META.sources || []).filter(s => s.enabled && s.kind !== "rera");
    const live = srcs.filter(s => s.last_status === "ok").length;
    const tile = (label, value, delta, cls = "", dcls = "") =>
      h("div", { class: "tile " + cls }, h("div", { class: "label" }, label), h("div", { class: "value" }, value),
        delta ? h("div", { class: "delta " + dcls }, delta) : null);
    $("kpis").replaceChildren(
      tile("Active listings", num(F.length), F.length !== ALL.length ? `of ${num(ALL.length)} in Coimbatore` : "across all sources", "hero"),
      tile("For sale", num(sale.length)),
      tile("For rent / lease", num(rent.length)),
      ppsf || !perCent
        ? tile("Median sale price", ppsf ? `₹${num(ppsf)}/sq ft` : "–", "flats, houses & villas")
        : tile("Median plot price", `${inr(perCent)}/cent`, "residential plots"),
      tile("Median rent", mrent ? inr(mrent, true) : "–", "flats, houses & villas"),
      tile("New this week", num(newN), drops ? `${num(drops)} price drops` : "", "", drops ? "good" : ""),
      tile("Sources live", srcs.length ? `${live} of ${srcs.length}` : "–", META.expired_last_run ? `${num(META.expired_last_run)} delisted last run` : ""),
    );
  }

  /* ------------------------------------------------------------ map */
  let map, cluster, heat, projLayer, tiles;
  function initMap() {
    map = L.map("map", { preferCanvas: false, zoomControl: true }).setView([11.0168, 76.9558], 12);
    setTiles();
    cluster = L.markerClusterGroup({
      chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: 50, spiderfyOnMaxZoom: true,
      iconCreateFunction: c => {
        const n = c.getChildCount(), size = n < 10 ? 30 : n < 100 ? 36 : n < 1000 ? 44 : 52;
        return L.divIcon({ html: `<div class="cluster" style="width:${size}px;height:${size}px">${n >= 1000 ? (n / 1000).toFixed(1) + "K" : n}</div>`, className: "", iconSize: [size, size] });
      },
    });
    map.addLayer(cluster);
    projLayer = L.layerGroup().addTo(map);
    map.on("moveend", renderInView);
    $("m-heat").addEventListener("change", renderMap);
    $("m-projects").addEventListener("change", renderProjectsLayer);
    $("inview-sort").addEventListener("change", renderInView);
  }
  function setTiles() {
    const dark = isDarkTheme();
    if (tiles) map.removeLayer(tiles);
    tiles = L.tileLayer(`https://{s}.basemaps.cartocdn.com/${dark ? "dark_all" : "light_all"}/{z}/{x}/{y}{r}.png`, {
      maxZoom: 19, subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);
  }
  function renderMap() {
    if (!map) return;
    cluster.clearLayers();
    if (heat) { map.removeLayer(heat); heat = null; }
    const pts = FILTERED.filter(l => l.latitude != null);
    const surface = cssVar("--surface-1");
    if ($("m-heat").checked) {
      heat = L.heatLayer(pts.map(l => [l.latitude, l.longitude, 0.6]), {
        radius: 22, blur: 24, maxZoom: 15,
        gradient: { 0.2: "#cde2fb", 0.4: "#86b6ef", 0.6: "#3987e5", 0.8: "#1c5cab", 1: "#0d366b" },
      }).addTo(map);
    } else {
      const markers = pts.map(l => {
        const m = L.circleMarker([l.latitude, l.longitude], {
          radius: 6, color: surface, weight: 2, fillColor: colorFor(l),
          fillOpacity: l.geo_precision === "exact" ? 0.95 : 0.45,
        });
        m.bindTooltip(`${priceText(l)} · ${TYPE_LABEL[l.property_type] || ""}`.replace(/</g, "&lt;"), { direction: "top", offset: [0, -6] });
        m.on("click", () => openDrawer(l));
        return m;
      });
      cluster.addLayers(markers);
    }
    renderProjectsLayer();
    renderInView();
  }
  function renderProjectsLayer() {
    if (!map) return;
    projLayer.clearLayers();
    if (!$("m-projects").checked) return;
    const icon = L.divIcon({ className: "", html: '<div class="proj-icon"></div>', iconSize: [12, 12] });
    for (const p of PROJECTS) {
      if (p.latitude == null) continue;
      const m = L.marker([p.latitude, p.longitude], { icon, keyboard: false });
      m.bindTooltip(`RERA · ${p.name || p.rera_id}`.replace(/</g, "&lt;"));
      m.on("click", () => { switchView("projects"); });
      projLayer.addLayer(m);
    }
  }
  function renderInView() {
    if (!map) return;
    const b = map.getBounds();
    let inView = FILTERED.filter(l => l.latitude != null && b.contains([l.latitude, l.longitude]));
    const unmapped = FILTERED.filter(l => l.latitude == null).length;
    const srt = $("inview-sort").value;
    const cmp = {
      new: (a, b2) => (b2.first_seen_at || "").localeCompare(a.first_seen_at || ""),
      "price-asc": (a, b2) => (a.price_inr ?? 1e15) - (b2.price_inr ?? 1e15),
      "price-desc": (a, b2) => (b2.price_inr ?? -1) - (a.price_inr ?? -1),
      "ppsf-asc": (a, b2) => (a.price_per_sqft ?? 1e15) - (b2.price_per_sqft ?? 1e15),
    }[srt];
    inView.sort(cmp);
    $("inview-count").textContent = num(inView.length);
    const list = $("inview-list");
    list.replaceChildren(...inView.slice(0, 150).map(card));
    if (inView.length > 150) list.append(h("li", { class: "more-note" }, `Showing 150 of ${num(inView.length)}. Zoom in, filter, or open the Listings tab.`));
    if (unmapped) list.append(h("li", { class: "more-note" }, `${num(unmapped)} matching listings have no map position; see the Listings tab.`));
  }
  function card(l) {
    const li = h("li", { class: "card", tabindex: 0 },
      h("div", {}, h("span", { class: "price" }, priceText(l)),
        l.price_per_sqft ? h("span", { class: "meta" }, `  ₹${num(l.price_per_sqft)}/sq ft`) : null),
      h("div", { class: "t" }, l.title || TYPE_LABEL[l.property_type]),
      h("div", { class: "meta" }, [l.locality || l.locality_raw, areaText(l), l.source_name].filter(x => x && x !== "–").join(" · ")),
      (l.is_new || l.previous_price_inr) ? h("div", {},
        l.is_new ? h("span", { class: "badge new" }, "New") : null,
        l.previous_price_inr ? h("span", { class: "badge drop" }, `↓ from ${inr(l.previous_price_inr, isRent(l))}`) : null) : null);
    li.addEventListener("click", () => openDrawer(l));
    li.addEventListener("keydown", e => { if (e.key === "Enter") openDrawer(l); });
    return li;
  }

  /* ------------------------------------------------------------ table */
  const COLS = [
    { key: "title", label: "Listing", get: l => l.title || "", render: l => h("td", {}, l.title || TYPE_LABEL[l.property_type], h("div", { class: "sub" }, [l.locality || l.locality_raw, l.project_name].filter(Boolean).join(" · "))) },
    { key: "property_type", label: "Type", get: l => TYPE_LABEL[l.property_type] || "" },
    { key: "transaction_type", label: "Deal", get: l => isRent(l) ? (l.transaction_type === "lease" ? "Lease" : "Rent") : "Sale" },
    { key: "bhk", label: "BHK", num: true, get: l => l.bhk, show: l => l.bhk ? trim(l.bhk) : "–" },
    { key: "area", label: "Area", num: true, get: l => areaSqft(l), show: areaText },
    { key: "price_inr", label: "Price", num: true, get: l => l.price_inr, show: priceText },
    { key: "price_per_sqft", label: "₹ / sq ft", num: true, get: l => l.price_per_sqft, show: l => l.price_per_sqft ? num(l.price_per_sqft) : "–" },
    { key: "posted_by", label: "Posted by", get: l => LABELS.posted_by[l.posted_by] || "" },
    { key: "source_name", label: "Source", get: l => l.source_name || "" },
    { key: "first_seen_at", label: "First seen", num: true, get: l => l.first_seen_at, show: l => dateText(l.first_seen_at) },
  ];
  function renderTable() {
    const thead = $("tbl").tHead;
    thead.replaceChildren(h("tr", {}, COLS.map(c => {
      const arrow = sort.key === c.key ? (sort.dir > 0 ? " ↑" : " ↓") : "";
      const th = h("th", { class: "sortable" + (c.num ? " num" : ""), "aria-sort": sort.key === c.key ? (sort.dir > 0 ? "ascending" : "descending") : null }, c.label + arrow);
      th.addEventListener("click", () => { sort = { key: c.key, dir: sort.key === c.key ? -sort.dir : (c.num ? -1 : 1) }; page = 0; renderTable(); });
      return th;
    })));
    const col = COLS.find(c => c.key === sort.key);
    const rows = [...FILTERED].sort((a, b) => {
      const x = col.get(a), y = col.get(b);
      if (x == null || x === "") return 1;
      if (y == null || y === "") return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * sort.dir;
    });
    const per = 50, pages = Math.max(1, Math.ceil(rows.length / per));
    page = Math.min(page, pages - 1);
    const tb = $("tbl").tBodies[0];
    tb.replaceChildren(...rows.slice(page * per, page * per + per).map(l => {
      const tr = h("tr", { class: "click", tabindex: 0 }, COLS.map(c => c.render ? c.render(l) : h("td", { class: c.num ? "num" : "" }, c.show ? c.show(l) : (c.get(l) || "–"))));
      tr.addEventListener("click", () => openDrawer(l));
      tr.addEventListener("keydown", e => { if (e.key === "Enter") openDrawer(l); });
      return tr;
    }));
    const pg = $("pager");
    pg.replaceChildren(
      h("button", { class: "btn", disabled: page === 0, onclick: () => { page--; renderTable(); } }, "← Prev"),
      h("span", {}, `Page ${page + 1} of ${pages} · ${num(rows.length)} listings`),
      h("button", { class: "btn", disabled: page >= pages - 1, onclick: () => { page++; renderTable(); } }, "Next →"));
  }

  /* ------------------------------------------------------------ insights */
  function chartCard(title, sub) {
    const body = h("div", {});
    const c = h("section", { class: "chart-card" }, h("h3", {}, title), h("p", { class: "csub" }, sub), body);
    $("charts").append(c);
    return { card: c, body };
  }
  function renderInsights() {
    $("charts").replaceChildren();
    const F = FILTERED;
    const series1 = "var(--series-1)";
    const typeScoped = state.types.length > 0;

    // 1. median ₹/sqft by locality
    {
      const pool = F.filter(l => l.transaction_type === "sale" && l.price_per_sqft && (typeScoped || BUILT.has(l.property_type)));
      const g = groupBy(pool, l => l.locality);
      const rows = Object.entries(g).filter(([k, v]) => k !== "undefined" && v.length >= 3)
        .map(([k, v]) => ({ label: k, value: median(v.map(x => x.price_per_sqft)), sub: `${v.length} listings` }))
        .sort((a, b) => b.value - a.value).slice(0, 15);
      const { card: c, body } = chartCard("Median sale price per sq ft, by locality",
        (typeScoped ? "Selected property types" : "Flats, houses & villas") + " · localities with 3+ listings · top 15");
      Charts.hbar(body, rows, { color: series1, fmt: v => "₹" + num(v) });
      if (rows.length) Charts.tableFallback(c, ["Locality", "Median ₹/sq ft", "Listings"], rows.map(r => [r.label, num(r.value), r.sub.split(" ")[0]]));
    }
    // 2. plot price per cent
    {
      const pool = F.filter(l => l.transaction_type === "sale" && l.property_type === "plot" && l.price_inr && l.plot_sqft);
      const g = groupBy(pool, l => l.locality);
      const rows = Object.entries(g).filter(([k, v]) => k !== "undefined" && v.length >= 2)
        .map(([k, v]) => ({ label: k, value: median(v.map(x => x.price_inr / (x.plot_sqft / SQFT_PER_CENT))), sub: `${v.length} plots` }))
        .sort((a, b) => b.value - a.value).slice(0, 15);
      const { card: c, body } = chartCard("Residential plot price per cent, by locality",
        "1 cent = 435.6 sq ft · localities with 2+ plots · top 15");
      Charts.hbar(body, rows, { color: series1, fmt: v => inr(v) });
      if (rows.length) Charts.tableFallback(c, ["Locality", "Median ₹/cent", "Plots"], rows.map(r => [r.label, inr(r.value), r.sub.split(" ")[0]]));
    }
    // 3. price distribution
    {
      const rentMode = state.deal === "rent";
      const pool = F.filter(l => (rentMode ? isRent(l) : l.transaction_type === "sale") && l.price_inr);
      const edges = rentMode ? [0, 5e3, 10e3, 15e3, 20e3, 30e3, 50e3, 1e5, Infinity] : [0, 25e5, 50e5, 75e5, 1e7, 1.5e7, 2e7, 3e7, 5e7, Infinity];
      const short = v => inr(v);
      const rows = edges.slice(0, -1).map((lo, i) => {
        const hi = edges[i + 1];
        const label = hi === Infinity ? `${short(lo)} and above` : lo ? `${short(lo)} – ${short(hi)}` : `Under ${short(hi)}`;
        return { label, value: pool.filter(l => l.price_inr >= lo && l.price_inr < hi).length };
      });
      const { card: c, body } = chartCard(rentMode ? "Monthly rent distribution" : "Sale price distribution",
        `${num(pool.length)} ${rentMode ? "rent / lease" : "sale"} listings with a price${rentMode ? "" : " · choose Rent to see rents"}`);
      Charts.hbar(body, rows, { color: series1, fmt: num, unit: "listings", labelWidth: 150 });
      Charts.tableFallback(c, ["Price band", "Listings"], rows.map(r => [r.label, num(r.value)]));
    }
    // 4. median rent by BHK
    {
      const pool = F.filter(l => isRent(l) && l.price_inr && l.bhk && BUILT.has(l.property_type));
      const g = groupBy(pool, l => Math.min(5, Math.floor(l.bhk)));
      const rows = [1, 2, 3, 4, 5].map(b => ({ label: b === 5 ? "5+ BHK" : `${b} BHK`, value: g[b] ? median(g[b].map(x => x.price_inr)) : 0, n: g[b]?.length || 0 }));
      const { card: c, body } = chartCard("Median monthly rent by bedrooms", "Flats, houses & villas for rent");
      Charts.columns(body, rows.map(r => ({ ...r, display: r.value ? inr(r.value) : "" })), { color: series1 });
      Charts.tableFallback(c, ["Bedrooms", "Median rent", "Listings"], rows.map(r => [r.label, r.value ? inr(r.value, true) : "–", num(r.n)]));
    }
    // 5. by type
    {
      const g = groupBy(F, l => l.property_type);
      const rows = Object.entries(g).map(([k, v]) => ({ label: TYPE_LABEL[k] || k, value: v.length })).sort((a, b) => b.value - a.value);
      const { card: c, body } = chartCard("Active listings by property type", "Current filters");
      Charts.hbar(body, rows, { color: series1, fmt: num, unit: "listings" });
      if (rows.length) Charts.tableFallback(c, ["Type", "Listings"], rows.map(r => [r.label, num(r.value)]));
    }
    // 6. by source
    {
      const g = groupBy(F, l => l.source_name || l.source_id);
      const rows = Object.entries(g).map(([k, v]) => ({ label: k, value: v.length })).sort((a, b) => b.value - a.value);
      const dup = F.filter(l => l.also_listed_on && l.also_listed_on.length).length;
      const { card: c, body } = chartCard("Active listings by source", dup ? `${num(dup)} adverts appear on more than one source` : "Current filters");
      Charts.hbar(body, rows, { color: series1, fmt: num, unit: "listings" });
      if (rows.length) Charts.tableFallback(c, ["Source", "Listings"], rows.map(r => [r.label, num(r.value)]));
    }
    // 7. weekly trend (whole market)
    {
      const tr = META.trend || [];
      const { card: c, body } = chartCard("Active listings, week by week", "Whole Coimbatore market · not affected by filters");
      Charts.lines(body, tr.map(t => dateText(t.taken_at).replace(/ \d{4}$/, "")), [
        { name: "Sale", color: "var(--series-1)", values: tr.map(t => t.sale || 0) },
        { name: "Rent", color: "var(--series-2)", values: tr.map(t => (t.rent || 0) + (t.lease || 0)) },
      ], { fmt: v => num(v) });
      if (tr.length) Charts.tableFallback(c, ["Week of", "Sale", "Rent / lease"], tr.map(t => [dateText(t.taken_at), num(t.sale), num((t.rent || 0) + (t.lease || 0))]));
    }
  }
  const groupBy = (arr, f) => arr.reduce((acc, x) => { const k = f(x); (acc[k] ||= []).push(x); return acc; }, {});

  /* ------------------------------------------------------------ projects & sources */
  function simpleTable(tbl, headers, rows) {
    tbl.tHead.replaceChildren(h("tr", {}, headers.map(x => h("th", {}, x))));
    tbl.tBodies[0].replaceChildren(...rows.map(r => h("tr", {}, r.map(c => h("td", {}, c)))));
  }
  function renderProjects() {
    const q = state.q.toLowerCase();
    const rows = PROJECTS.filter(p => !q || [p.name, p.promoter, p.locality, p.rera_id, p.address].join(" ").toLowerCase().includes(q))
      .filter(p => !state.locs.length || state.locs.includes(p.locality || "(unmapped)"));
    simpleTable($("ptbl"), ["RERA number", "Project", "Promoter", "Type", "Locality", "Registered", "Completion"],
      rows.map(p => [
        safeUrl(p.url) ? h("a", { href: safeUrl(p.url), target: "_blank", rel: "noopener noreferrer" }, p.rera_id) : p.rera_id,
        p.name || "–", p.promoter || "–", p.project_type || "–", p.locality || h("span", { class: "sub" }, p.address || "–"),
        p.registered_on || "–", p.completion_date || "–",
      ]));
    if (!rows.length) $("ptbl").tBodies[0].append(h("tr", {}, h("td", { colspan: 7, class: "muted" }, PROJECTS.length ? "No projects match the search / locality filter." : "No RERA projects collected yet.")));
  }
  function renderSources() {
    const label = { ok: "OK", blocked: "Blocked", failed: "Failed", suspicious: "Low yield", skipped: "Skipped" };
    simpleTable($("stbl"), ["Source", "Kind", "Last run", "Status", "Records", "Active listings", "Note"],
      (META.sources || []).map(s => [
        s.name, s.kind, dateText(s.last_run_at),
        s.enabled ? (s.last_status ? h("span", { class: "status " + s.last_status }, label[s.last_status] || s.last_status) : "Not run yet") : "Disabled",
        s.last_records == null ? "–" : num(s.last_records), num(s.active_listings), s.message || "",
      ]));
  }

  /* ------------------------------------------------------------ drawer */
  function openDrawer(l) {
    const rent = isRent(l);
    const rows = [
      ["Type", TYPE_LABEL[l.property_type]], ["Deal", rent ? (l.transaction_type === "lease" ? "Lease" : "Rent") : "Sale"],
      ["Bedrooms", l.bhk ? `${trim(l.bhk)} BHK` : null], ["Bathrooms", l.bathrooms],
      ["Area", areaSqft(l) ? areaText(l) : null], ["Carpet area", l.carpet_sqft ? num(l.carpet_sqft) + " sq ft" : null],
      ["Price per sq ft", l.price_per_sqft ? "₹" + num(l.price_per_sqft) : null],
      ["Price per cent", l.property_type === "plot" && l.price_inr && l.plot_sqft ? inr(l.price_inr / (l.plot_sqft / SQFT_PER_CENT)) : null],
      ["Deposit", l.deposit_inr ? inr(l.deposit_inr) : null],
      ["Furnishing", LABELS.furnishing[l.furnishing]], ["Construction", LABELS.construction_status[l.construction_status]],
      ["Facing", l.facing ? l.facing[0].toUpperCase() + l.facing.slice(1) : null],
      ["Locality", [l.locality || l.locality_raw, l.zone ? `${l.zone} zone` : null].filter(Boolean).join(" · ") || null],
      ["Pincode", l.pincode], ["Project", l.project_name], ["Builder", l.builder],
      ["Posted by", [LABELS.posted_by[l.posted_by], l.advertiser].filter(Boolean).join(" · ") || null],
      ["RERA", l.rera_id], ["Approvals mentioned", (l.approvals || []).join(", ") || null],
      ["Map position", l.geo_precision === "exact" ? "Exact (from source)" : l.geo_precision === "locality" ? "Approximate (locality centre)" : "Unknown"],
      ["Source", l.source_name], ["First seen", dateText(l.first_seen_at)], ["Last confirmed", dateText(l.last_seen_at)],
    ].filter(([, v]) => v != null && v !== "");
    const img = (l.images || []).map(safeUrl).find(Boolean);
    const body = $("drawer-body");
    const proj = l.rera_id && PROJECTS.find(p => p.rera_id === l.rera_id);
    body.replaceChildren(...[
      h("h2", {}, l.title || TYPE_LABEL[l.property_type]),
      h("div", { class: "muted" }, [l.locality || l.locality_raw, "Coimbatore"].filter(Boolean).join(", ")),
      h("div", { class: "price-big" }, priceText(l)),
      l.previous_price_inr ? h("span", { class: "badge drop" }, `Reduced from ${inr(l.previous_price_inr, rent)}`) : null,
      l.is_new ? h("span", { class: "badge new" }, "New this week") : null,
      img ? h("img", { class: "photo", src: img, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : null,
      h("dl", {}, rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))])),
      proj ? h("p", { class: "note" }, `✓ RERA number matches registered project “${proj.name || proj.rera_id}” by ${proj.promoter || "unknown promoter"}.`) : null,
      l.also_listed_on && l.also_listed_on.length ? [
        h("h3", {}, "Also listed on"),
        h("table", { class: "data" }, h("tbody", {}, l.also_listed_on.map(a => h("tr", {},
          h("td", {}, safeUrl(a.url) ? h("a", { href: safeUrl(a.url), target: "_blank", rel: "noopener noreferrer" }, a.source) : a.source),
          h("td", { class: "num" }, inr(a.price_inr, rent)))))),
      ] : null,
      (l.amenities || []).length ? [h("h3", {}, "Amenities"), h("p", {}, l.amenities.join(", "))] : null,
      h("div", { class: "actions" },
        safeUrl(l.url) ? h("a", { class: "btn", href: safeUrl(l.url), target: "_blank", rel: "noopener noreferrer" }, `Open on ${l.source_name || "source"} ↗`) : null,
        l.latitude != null ? h("a", { class: "btn", href: `https://www.google.com/maps/search/?api=1&query=${l.latitude},${l.longitude}`, target: "_blank", rel: "noopener noreferrer" }, "Google Maps ↗") : null,
        l.latitude != null && map ? h("button", { class: "btn", onclick: () => { switchView("map"); map.setView([l.latitude, l.longitude], 16); } }, "Show on map") : null),
    ].flat().filter(x => x != null && x !== false));
    $("drawer").classList.add("open");
    $("drawer").setAttribute("aria-hidden", "false");
    $("drawer-close").focus();
  }
  function closeDrawer() { $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); }

  /* ------------------------------------------------------------ export */
  function exportCsv() {
    const cols = ["title", "transaction_type", "property_type", "bhk", "built_up_sqft", "plot_sqft", "area_unit_original",
      "area_value_original", "price_inr", "price_per_sqft", "locality", "pincode", "latitude", "longitude", "geo_precision",
      "posted_by", "advertiser", "project_name", "builder", "rera_id", "source_name", "url", "first_seen_at", "last_seen_at"];
    const esc = v => {
      if (v == null) return "";
      let s = String(v);
      if (/^[=+\-@]/.test(s)) s = "'" + s; // neutralise spreadsheet formulas from scraped text
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csv = [cols.join(","), ...FILTERED.map(l => cols.map(c => esc(l[c])).join(","))].join("\n");
    const a = h("a", { href: URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" })), download: `coimbatore-listings-${new Date().toISOString().slice(0, 10)}.csv` });
    // Embedded/sandboxed hosts block downloads: copy to the clipboard instead.
    if (window.self !== window.top && navigator.clipboard) {
      navigator.clipboard.writeText(csv).then(
        () => flash(`Copied ${num(FILTERED.length)} rows as CSV`),
        () => flash("Export is blocked here"));
      return;
    }
    document.body.append(a); a.click(); a.remove();
  }

  function flash(msg) {
    const b = $("export"), old = "Export CSV";
    b.textContent = msg;
    setTimeout(() => { b.textContent = old; }, 2500);
  }

  /* ------------------------------------------------------------ view switching */
  function switchView(v) {
    view = v;
    document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.view === v)));
    for (const id of ["map", "list", "insights", "projects", "sources"]) $("view-" + id).hidden = id !== v;
    const noData = !ALL.length && ["map", "list", "insights"].includes(v);
    $("empty").hidden = !noData;
    if (noData) $("view-" + v).hidden = true;
    renderView();
    writeHash();
  }
  function renderView() {
    if (view === "map" && map) { map.invalidateSize(); fitToResults(); renderMap(); }
    if (view === "list") renderTable();
    if (view === "insights") renderInsights();
    if (view === "projects") renderProjects();
    if (view === "sources") renderSources();
  }

  let lastFitKey = null;
  function fitToResults() {
    if (!map) return;
    const key = JSON.stringify(state);
    if (key === lastFitKey) return;
    lastFitKey = key;
    const pts = FILTERED.filter(l => l.latitude != null).map(l => [l.latitude, l.longitude]);
    if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.1), { maxZoom: 15, animate: false });
  }
  function update() {
    FILTERED = ALL.filter(l => matches(l));
    page = 0;
    $("count").textContent = ALL.length ? `${num(FILTERED.length)} of ${num(ALL.length)} listings` : "";
    syncControls();
    buildFilterControls();
    renderKpis();
    renderView();
    writeHash();
  }

  function renderEmpty() {
    $("empty").replaceChildren(
      h("h2", {}, "No listings collected yet"),
      h("p", {}, "The collector runs every Monday morning (IST) on GitHub Actions and publishes here. To fill the dashboard now, run it once by hand:"),
      h("ol", {},
        h("li", {}, "Open the repository's Actions tab → “Weekly listings refresh” → Run workflow."),
        h("li", {}, "Wait for it to finish (it is deliberately slow and polite to each site), then reload this page.")),
      h("p", {}, "The Sources tab shows what each source returned on the last run.")
    );
  }

  /* ------------------------------------------------------------ theme */
  const isDarkTheme = () => document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  const themeLabel = () => { $("theme").textContent = isDarkTheme() ? "Light mode" : "Dark mode"; };
  function wireTheme() {
    let saved = null;
    try { saved = localStorage.getItem("cpi-theme"); } catch { /* storage unavailable */ }
    if (saved) document.documentElement.dataset.theme = saved;
    themeLabel();
    $("theme").addEventListener("click", () => {
      document.documentElement.dataset.theme = isDarkTheme() ? "light" : "dark";
      try { localStorage.setItem("cpi-theme", document.documentElement.dataset.theme); } catch { /* ignore */ }
      themeLabel();
      if (map) { setTiles(); }
      renderView();
    });
  }

  /* ------------------------------------------------------------ boot */
  async function boot() {
    wireTheme();
    readHash();
    await load();
    wireFilters();
    renderEmpty();
    document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));
    $("drawer-close").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
    initMap();
    let rt;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (view === "insights") renderInsights(); }, 150); });
    FILTERED = ALL.filter(l => matches(l));
    switchView(view);
    update();
    window.addEventListener("hashchange", () => { Object.assign(state, defaults()); readHash(); switchView(view); update(); });
  }
  boot();
})();
