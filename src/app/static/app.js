/* Modo Guerrero — interfaz web (sin framework) */
"use strict";

// ---------------------------------------------------------------- utilidades
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

async function api(path, opts = {}) {
  const o = { headers: { "X-Requested-With": "modo-guerrero" }, credentials: "same-origin", ...opts };
  if (o.body && !(o.body instanceof FormData)) {
    o.headers["Content-Type"] = "application/json";
    o.body = JSON.stringify(o.body);
  }
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch { /* vacío */ }
  if (r.status === 401 && data && data.auth) {
    // sesión caducada o cerrada: volver a la pantalla de acceso
    AUTHED = false;
    showAuth(false);
    throw new Error("Inicia sesión");
  }
  if (!r.ok) throw new Error((data && data.detail) || `Error ${r.status}`);
  return data;
}
let AUTHED = false;
let ME = null;

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 3800);
}

// ---- formatos
const nf1 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 });
const km = (m) => (m == null ? "–" : nf1.format(m / 1000));
const int = (v) => (v == null || isNaN(v) ? "–" : nf0.format(v));
function dur(s, short = false) {
  if (s == null || isNaN(s)) return "–";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (short && h) return `${h} h ${String(m).padStart(2, "0")} min`;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}
function pace(secPerKm) {
  if (!secPerKm || !isFinite(secPerKm)) return "–";
  const s = Math.round(secPerKm);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
const paceOf = (a) => (a.distance_m ? a.moving_s / (a.distance_m / 1000) : null);
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const MONTHS_FULL = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const WEEKDAYS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
function fdate(iso, withYear = true) {
  if (!iso) return "–";
  const d = new Date(iso.slice(0, 10) + "T12:00:00");
  return `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}${withYear ? " " + d.getFullYear() : ""}`;
}
const fdateShort = (iso) => { const d = new Date(iso.slice(0, 10) + "T12:00:00"); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const hours = (s) => (s == null ? "–" : `${Math.floor(s / 3600)} h ${String(Math.round((s % 3600) / 60)).padStart(2, "0")}`);
function delta(cur, prev, unit = "", invert = false) {
  if (prev == null || cur == null || prev === 0) return `<span class="delta flat">—</span>`;
  const d = cur - prev;
  const pct = Math.round((d / prev) * 100);
  const good = invert ? d < 0 : d > 0;
  const cls = Math.abs(pct) < 3 ? "flat" : good ? "up" : "down";
  return `<span class="delta ${cls}">${d > 0 ? "▲" : d < 0 ? "▼" : ""} ${Math.abs(pct)}%${unit}</span>`;
}
const SPORT = { running: "Carrera", trail_running: "Trail", treadmill_running: "Cinta", track_running: "Pista", indoor_running: "Interior", street_running: "Asfalto", ultra_run: "Ultra", virtual_run: "Virtual", obstacle_run: "Obstáculos" };
const sportName = (s) => SPORT[s] || (s || "").replace(/_/g, " ");

const TRAINING_STATUS = {
  PRODUCTIVE: ["Productivo", "good"], MAINTAINING: ["Mantenimiento", "blue"], RECOVERY: ["Recuperación", "blue"],
  UNPRODUCTIVE: ["Improductivo", "warn"], DETRAINING: ["Pérdida de forma", "bad"], OVERREACHING: ["Sobrecarga", "bad"],
  PEAKING: ["En pico", "good"], STRAINED: ["Exigido", "warn"], NO_STATUS: ["Sin estado", ""], PAUSED: ["En pausa", ""],
};
function trainingStatus(snap) {
  const phrase = (snap && snap.status_phrase) || "";
  const key = phrase.replace(/_\d+$/, "").toUpperCase();
  return TRAINING_STATUS[key] || (phrase ? [phrase.replace(/_/g, " ").toLowerCase(), ""] : null);
}
const HRV_STATUS = { BALANCED: ["Equilibrada", "good"], UNBALANCED: ["Desequilibrada", "warn"], LOW: ["Baja", "bad"], POOR: ["Muy baja", "bad"], NONE: ["Sin datos", ""] };
const READY = { PRIME: ["Óptima", "good"], HIGH: ["Alta", "good"], MODERATE: ["Moderada", "blue"], LOW: ["Baja", "warn"], POOR: ["Muy baja", "bad"] };
function tsbLabel(tsb) {
  if (tsb == null) return ["–", ""];
  if (tsb > 15) return ["Muy fresco", "blue"];
  if (tsb > 5) return ["Fresco", "good"];
  if (tsb > -10) return ["Neutral", ""];
  if (tsb > -30) return ["Cargando", "warn"];
  return ["Riesgo de sobrecarga", "bad"];
}

// ---------------------------------------------------------------- tema
const ACCENTS = [["#ff6b2c", "Naranja"], ["#ef4444", "Rojo"], ["#ec4899", "Rosa"], ["#8b5cf6", "Violeta"],
  ["#3b82f6", "Azul"], ["#14b8a6", "Turquesa"], ["#22c55e", "Verde"], ["#eab308", "Amarillo"]];
const THEMES = [["auto", "Automático"], ["light", "Claro"], ["dark", "Oscuro"], ["black", "Negro"]];
function applyTheme(theme, accent, save = true) {
  const root = document.documentElement;
  if (!theme || theme === "auto") delete root.dataset.theme; else root.dataset.theme = theme;
  if (accent) root.style.setProperty("--accent", accent);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = css("--bg");
  if (save) { try { localStorage.setItem("mg_theme", JSON.stringify({ theme, accent })); } catch { /* sin almacenamiento */ } }
}
// en modo automático, repintar gráficas si el sistema cambia entre claro y oscuro
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!document.documentElement.dataset.theme && AUTHED) { applyTheme("auto", null, false); rerender(); }
});

// ---------------------------------------------------------------- gráficas
let charts = [];
let maps = [];
function disposeAll() {
  charts.forEach((c) => c.dispose());
  maps.forEach((m) => m.remove());
  charts = [];
  maps = [];
}
window.addEventListener("resize", () => charts.forEach((c) => c.resize()));

function theme() {
  return {
    text: css("--muted"), faint: css("--faint"), line: css("--line"), card: css("--card-2"), fg: css("--text"),
    accent: css("--accent"), good: css("--good"), warn: css("--warn"), bad: css("--bad"), blue: css("--blue"), violet: css("--violet"),
  };
}
function chart(el, option) {
  if (!el) return null;
  const t = theme();
  const c = echarts.init(el, null, { renderer: "canvas" });
  const base = {
    textStyle: { color: t.text, fontFamily: "inherit" },
    animationDuration: 500,
    grid: { left: 8, right: 10, top: 20, bottom: 4, containLabel: true },
    tooltip: {
      trigger: "axis", backgroundColor: t.card, borderColor: t.line, textStyle: { color: t.fg, fontSize: 12 },
      axisPointer: { lineStyle: { color: t.faint } },
    },
  };
  const axis = (a) => (a ? [].concat(a).map((x) => ({
    axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false },
    splitLine: { lineStyle: { color: t.line, type: "dashed" } }, axisLabel: { color: t.text, fontSize: 11 }, ...x,
  })) : undefined);
  c.setOption({ ...base, ...option, xAxis: axis(option.xAxis), yAxis: axis(option.yAxis), tooltip: { ...base.tooltip, ...(option.tooltip || {}) } });
  charts.push(c);
  return c;
}
function sparkline(el, values, color) {
  const t = theme();
  return chart(el, {
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    tooltip: { show: false },
    xAxis: { type: "category", show: false, data: values.map((_, i) => i) },
    yAxis: { type: "value", show: false, scale: true },
    series: [{ type: "line", data: values, smooth: true, symbol: "none", lineStyle: { width: 2, color: color || t.accent },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: (color || t.accent) + "55" }, { offset: 1, color: (color || t.accent) + "00" }]) } }],
  });
}
function map(el, latlngs, opts = {}) {
  if (!el || !latlngs || !latlngs.length) return null;
  const m = L.map(el, { zoomControl: !!opts.zoom, attributionControl: true, scrollWheelZoom: !!opts.zoom, dragging: opts.zoom !== false || !L.Browser.mobile });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
  const accent = css("--accent");
  const line = L.polyline(latlngs, { color: accent, weight: 4, opacity: 0.95 }).addTo(m);
  L.circleMarker(latlngs[0], { radius: 6, color: "#fff", weight: 2, fillColor: css("--good"), fillOpacity: 1 }).addTo(m);
  L.circleMarker(latlngs[latlngs.length - 1], { radius: 6, color: "#fff", weight: 2, fillColor: css("--bad"), fillOpacity: 1 }).addTo(m);
  m.fitBounds(line.getBounds(), { padding: [16, 16] });
  maps.push(m);
  return m;
}

// ---------------------------------------------------------------- estado / sync
let STATUS = null;
async function refreshStatus() {
  if (!AUTHED) return;
  try {
    STATUS = await api("/api/status");
  } catch { return; }
  const pill = $("#syncBtn"), text = $("#syncText"), s = STATUS.sync;
  $("#version").textContent = "v" + STATUS.version;
  pill.className = "sync-pill";
  if (s.running) {
    pill.classList.add("run");
    text.textContent = s.phase || "Sincronizando…";
  } else if (!STATUS.connected) {
    pill.classList.add("err");
    text.textContent = "Sin conectar";
  } else if (s.last_error) {
    pill.classList.add("err");
    text.textContent = "Error de sincronización";
  } else {
    pill.classList.add("ok");
    const last = STATUS.last_log && STATUS.last_log.finished;
    text.textContent = last ? `Sincronizado ${timeAgo(last)}` : "Conectado";
  }
  const b = $("#banner");
  const isSettings = location.hash.startsWith("#/ajustes");
  if (!STATUS.connected && STATUS.counts.total === 0 && !isSettings) {
    b.className = "banner info"; b.hidden = false;
    b.innerHTML = `<span>Conecta tu cuenta de Garmin para empezar a importar tus carreras.</span><a class="btn primary small" href="#/ajustes">Conectar Garmin</a>`;
  } else if (STATUS.last_log && STATUS.last_log.status === "auth" && !isSettings) {
    b.className = "banner"; b.hidden = false;
    b.innerHTML = `<span><b>Sesión de Garmin caducada.</b> Última sincronización correcta: ${s.last_ok ? timeAgo(s.last_ok) : "desconocida"}.</span><a class="btn small" href="#/ajustes">Reconectar</a>`;
  } else b.hidden = true;
  clearTimeout(refreshStatus._t);
  refreshStatus._t = setTimeout(refreshStatus, s.running ? 4000 : 60000);
  if (refreshStatus._wasRunning && !s.running) rerender();
  refreshStatus._wasRunning = s.running;
}
function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 60000;
  if (diff < 1) return "ahora";
  if (diff < 60) return `hace ${Math.round(diff)} min`;
  if (diff < 1440) return `hace ${Math.round(diff / 60)} h`;
  return `el ${fdateShort(iso)}`;
}
$("#syncBtn").addEventListener("click", async () => {
  if (!STATUS || !STATUS.connected) { location.hash = "#/ajustes"; return; }
  try { await api("/api/sync", { method: "POST" }); toast("Sincronización iniciada"); setTimeout(refreshStatus, 800); }
  catch (e) { toast(e.message, true); }
});

// ---------------------------------------------------------------- router
const routes = {};
let current = null;
function route(name, fn) { routes[name] = fn; }
async function rerender() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [name, ...args] = hash.split("/");
  const key = name || "home";
  current = key;
  disposeAll();
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === (key === "carrera" ? "carreras" : key)));
  const view = $("#view");
  view.innerHTML = `<div class="skeleton"></div>`;
  try {
    await (routes[key] || routes.home)(view, ...args);
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="empty"><h2>Algo ha fallado</h2><p>${esc(e.message)}</p></div>`;
  }
  refreshStatus();
}
window.addEventListener("hashchange", () => { if (!AUTHED) return; window.scrollTo(0, 0); rerender(); });

// ================================================================ INICIO
const WIDGETS = {
  week: { title: "Esta semana", render: wWeek },
  month: { title: "Mes y año", render: wMonth },
  fitness: { title: "Forma y carga", render: wFitness },
  health: { title: "Salud de hoy", render: wHealth },
  last: { title: "Última carrera", render: wLast },
  records: { title: "Récords personales", render: wRecords },
  predictions: { title: "Predicciones de carrera", render: wPredictions },
  weeks_chart: { title: "Kilómetros por semana", render: wWeeksChart },
};

route("home", async (view) => {
  const [data, settings] = await Promise.all([api("/api/home"), api("/api/settings")]);
  const hasData = data.last || data.health.length;
  view.innerHTML = `
    <div class="page-head">
      <div><h1>${greeting()}</h1><div class="sub">${fdate(data.today)}</div></div>
      <div class="row"><button class="btn" id="editBtn">Personalizar inicio</button></div>
    </div>
    ${hasData ? "" : `<div class="card empty"><h2>Aún no hay datos</h2><p>Cuando conectes Garmin y termine la primera sincronización, aquí verás tu resumen. También puedes importar archivos .FIT desde Ajustes.</p><a class="btn primary" href="#/ajustes">Ir a Ajustes</a></div><br>`}
    <div class="grid" id="widgets"></div>
    <div class="hidden-tray" id="tray" hidden><b>Widgets ocultos</b><div class="row" id="trayList"></div></div>`;
  const grid = $("#widgets");
  const ws = settings.widgets;
  for (const w of ws) {
    if (!w.visible || !WIDGETS[w.id]) continue;
    const card = document.createElement("section");
    card.className = "card" + (w.wide ? " wide" : "");
    card.dataset.id = w.id;
    grid.appendChild(card);
    const after = WIDGETS[w.id].render(card, data);
    card.insertAdjacentHTML("beforeend", `<div class="edit-bar"><button data-act="wide">${w.wide ? "Estrecho" : "Ancho"}</button><button data-act="hide">Ocultar</button></div>`);
    if (after) after();
  }
  setupEditing(ws);
});

function greeting() {
  const h = new Date().getHours();
  return h < 13 ? "Buenos días" : h < 21 ? "Buenas tardes" : "Buenas noches";
}

function setupEditing(ws) {
  const grid = $("#widgets"), btn = $("#editBtn"), tray = $("#tray");
  let sortable = null;
  const save = async () => {
    const order = $$(".card", grid).map((c) => c.dataset.id);
    const byId = Object.fromEntries(ws.map((w) => [w.id, w]));
    const visible = order.map((id) => byId[id]);
    const hidden = ws.filter((w) => !order.includes(w.id));
    const next = [...visible, ...hidden];
    ws.splice(0, ws.length, ...next);
    await api("/api/settings", { method: "PUT", body: { widgets: next } });
  };
  const renderTray = () => {
    const hidden = ws.filter((w) => !w.visible);
    $("#trayList").innerHTML = hidden.length
      ? hidden.map((w) => `<button class="btn small" data-show="${w.id}">+ ${esc(WIDGETS[w.id]?.title || w.id)}</button>`).join("")
      : `<span class="muted">Todos los widgets están visibles.</span>`;
  };
  btn.onclick = async () => {
    const on = !grid.classList.contains("editing");
    grid.classList.toggle("editing", on);
    btn.textContent = on ? "Listo" : "Personalizar inicio";
    btn.classList.toggle("primary", on);
    tray.hidden = !on;
    if (on) {
      renderTray();
      sortable = Sortable.create(grid, { animation: 150, onEnd: save });
    } else {
      sortable && sortable.destroy();
      await save();
      toast("Inicio guardado");
    }
  };
  grid.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const card = b.closest(".card"), w = ws.find((x) => x.id === card.dataset.id);
    if (b.dataset.act === "hide") { w.visible = false; card.remove(); renderTray(); }
    if (b.dataset.act === "wide") { w.wide = !w.wide; card.classList.toggle("wide", w.wide); b.textContent = w.wide ? "Estrecho" : "Ancho"; charts.forEach((c) => c.resize()); }
    await save();
  });
  tray.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-show]");
    if (!b) return;
    ws.find((x) => x.id === b.dataset.show).visible = true;
    await save();
    await rerender();
    $("#editBtn").click();
  });
}

function wWeek(card, d) {
  const c = d.week.current, ps = d.week.previous_same, goal = d.week.goal_km;
  const kmNow = c.dist / 1000;
  const pct = goal ? Math.min(100, (kmNow / goal) * 100) : 0;
  card.innerHTML = `
    <h3>Esta semana <span class="tag">${c.n} ${c.n === 1 ? "carrera" : "carreras"}</span></h3>
    <div class="row" style="align-items:baseline"><div class="big num">${km(c.dist)}<small>km</small></div>${delta(c.dist, ps.dist)}</div>
    <div class="muted" style="font-size:13px">frente al mismo punto de la semana pasada (${km(ps.dist)} km)</div>
    ${goal ? `<div class="progress"><div style="width:${pct}%"></div></div><div class="muted" style="font-size:12px">${Math.round(pct)}% del objetivo de ${goal} km</div>` : ""}
    <div class="kpis">
      <div class="kpi"><div class="v num">${dur(c.secs, true)}</div><div class="l">Tiempo</div></div>
      <div class="kpi"><div class="v num">${pace(c.pace)}</div><div class="l">Ritmo medio /km</div></div>
      <div class="kpi"><div class="v num">${int(c.elev)} m</div><div class="l">Desnivel +</div></div>
      <div class="kpi"><div class="v num">${km(d.week.previous.dist)}</div><div class="l">Semana pasada (km)</div></div>
    </div>`;
}

function wMonth(card, d) {
  const m = d.month, mk = m.current.dist / 1000, yk = m.year.dist / 1000;
  const mp = m.goal_km ? Math.min(100, (mk / m.goal_km) * 100) : 0;
  const yp = m.yearly_goal_km ? Math.min(100, (yk / m.yearly_goal_km) * 100) : 0;
  const now = new Date();
  const dayOfYear = Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 864e5);
  const projection = (yk / dayOfYear) * (new Date(now.getFullYear(), 11, 31) - new Date(now.getFullYear(), 0, 0)) / 864e5;
  card.innerHTML = `
    <h3>Mes y año</h3>
    <div class="row" style="justify-content:space-between;align-items:baseline">
      <div><div class="muted" style="font-size:13px">${MONTHS_FULL[now.getMonth()]}</div><div class="mid num">${km(m.current.dist)} km ${delta(m.current.dist, m.previous_same.dist)}</div></div>
      <div style="text-align:right"><div class="muted" style="font-size:13px">${m.current.n} carreras</div><div class="muted num" style="font-size:13px">${pace(m.current.pace)} /km</div></div>
    </div>
    ${m.goal_km ? `<div class="progress"><div style="width:${mp}%"></div></div><div class="muted" style="font-size:12px">${Math.round(mp)}% de ${m.goal_km} km</div>` : ""}
    <div class="row" style="justify-content:space-between;align-items:baseline;margin-top:16px">
      <div><div class="muted" style="font-size:13px">${now.getFullYear()}</div><div class="mid num">${km(m.year.dist)} km ${delta(m.year.dist, m.prev_year_same.dist)}</div></div>
      <div style="text-align:right"><div class="muted" style="font-size:13px">${m.year.n} carreras</div><div class="muted num" style="font-size:13px">proyección ${int(projection)} km</div></div>
    </div>
    ${m.yearly_goal_km ? `<div class="progress"><div style="width:${yp}%"></div></div><div class="muted" style="font-size:12px">${Math.round(yp)}% de ${m.yearly_goal_km} km · año pasado a estas alturas: ${km(m.prev_year_same.dist)} km</div>` : ""}`;
}

function wFitness(card, d) {
  const f = d.fitness, last = f[f.length - 1] || {}, snap = d.snapshot || {};
  const [tl, tc] = tsbLabel(last.tsb);
  const st = trainingStatus(snap);
  card.innerHTML = `
    <h3>Forma y carga ${st ? `<span class="tag ${st[1]}">${esc(st[0])}</span>` : ""}</h3>
    <div class="kpis" style="margin-top:0">
      <div class="kpi"><div class="v num">${last.ctl != null ? nf0.format(last.ctl) : "–"}</div><div class="l">Fitness (CTL)</div></div>
      <div class="kpi"><div class="v num">${last.atl != null ? nf0.format(last.atl) : "–"}</div><div class="l">Fatiga (ATL)</div></div>
      <div class="kpi"><div class="v num">${last.tsb != null ? nf0.format(last.tsb) : "–"}</div><div class="l">Forma (TSB) <span class="tag ${tc}" style="font-size:10px;padding:1px 5px">${tl}</span></div></div>
      <div class="kpi"><div class="v num">${snap.vo2max ? nf1.format(snap.vo2max) : "–"}</div><div class="l">VO2max</div></div>
    </div>
    <div class="chart" id="cFit" style="height:140px;margin-top:10px"></div>
    ${snap.acute_load ? `<div class="muted" style="font-size:12px">Garmin: carga aguda ${int(snap.acute_load)} · crónica ${int(snap.chronic_load)}${snap.acwr ? ` · ratio ${nf1.format(snap.acwr)}` : ""}</div>` : ""}
    <a class="more" href="#/forma">Ver evolución →</a>`;
  return () => fitnessChart($("#cFit", card), f, false);
}

function fitnessChart(el, f, full) {
  const t = theme();
  return chart(el, {
    grid: { left: 4, right: 4, top: full ? 34 : 6, bottom: full ? 30 : 2, containLabel: true },
    legend: full ? { top: 0, textStyle: { color: t.text }, icon: "roundRect" } : undefined,
    xAxis: { type: "category", data: f.map((x) => x.date), axisLabel: { show: full, formatter: (v) => fdateShort(v) }, boundaryGap: false },
    yAxis: [{ type: "value", axisLabel: { show: full } }, { type: "value", show: false }],
    dataZoom: full ? [{ type: "inside" }, { type: "slider", height: 18, bottom: 4, borderColor: t.line, textStyle: { color: t.text } }] : undefined,
    tooltip: { formatter: (ps) => `${fdate(ps[0].axisValue)}<br>` + ps.map((p) => `${p.marker}${p.seriesName}: <b>${nf0.format(p.value)}</b>`).join("<br>") },
    series: [
      { name: "Fitness (CTL)", type: "line", data: f.map((x) => x.ctl), smooth: true, symbol: "none", lineStyle: { width: 2.5, color: t.blue },
        areaStyle: { color: t.blue + "22" }, itemStyle: { color: t.blue } },
      { name: "Fatiga (ATL)", type: "line", data: f.map((x) => x.atl), smooth: true, symbol: "none", lineStyle: { width: 1.5, color: t.violet }, itemStyle: { color: t.violet } },
      ...(!full ? [] : [{ name: "Forma (TSB)", type: "bar", yAxisIndex: 0, data: f.map((x) => ({ value: x.tsb, itemStyle: { color: x.tsb >= 0 ? t.good + "aa" : t.warn + "aa" } })), barCategoryGap: "20%", itemStyle: { color: t.good } }]),
      ...(full ? [{ name: "Carga diaria", type: "scatter", data: f.map((x) => x.load || null), symbolSize: 5, itemStyle: { color: t.accent }, yAxisIndex: 0 }] : []),
    ],
  });
}

function wHealth(card, d) {
  const H = [...d.health].reverse(); // cronológico
  const today = d.health[0] || {};
  const sleepDay = d.health.find((x) => x.sleep_s) || {};
  const hs = HRV_STATUS[(today.hrv_status || "").toUpperCase()];
  const rd = READY[(today.readiness_level || "").toUpperCase()];
  const avg = (k, n = 7) => { const v = H.slice(-n).map((x) => x[k]).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  if (!d.health.length) { card.innerHTML = `<h3>Salud de hoy</h3><div class="muted">Sin datos de salud todavía.</div>`; return; }
  card.innerHTML = `
    <h3>Salud de hoy ${rd ? `<span class="tag ${rd[1]}">Disposición ${rd[0].toLowerCase()} · ${int(today.readiness)}</span>` : ""}</h3>
    <div class="health-grid">
      <div class="hm"><div class="l"><span>Sueño</span><span>${sleepDay.sleep_score ? "puntuación " + sleepDay.sleep_score : ""}</span></div>
        <div class="v num">${hours(sleepDay.sleep_s)}</div><div class="spark" id="sSleep"></div></div>
      <div class="hm"><div class="l"><span>VFC nocturna</span>${hs ? `<span class="tag ${hs[1]}" style="font-size:10px;padding:1px 5px">${hs[0]}</span>` : ""}</div>
        <div class="v num">${int(today.hrv_night)} <small>ms · media 7 d ${int(today.hrv_weekly)}</small></div><div class="spark" id="sHrv"></div></div>
      <div class="hm"><div class="l"><span>FC en reposo</span><span>media 7 d ${int(avg("rhr"))}</span></div>
        <div class="v num">${int(today.rhr)} <small>ppm</small></div><div class="spark" id="sRhr"></div></div>
      <div class="hm"><div class="l"><span>Body Battery</span><span>${today.bb_low != null ? `mín ${today.bb_low} · máx ${today.bb_high}` : ""}</span></div>
        <div class="v num">${int(today.bb_last ?? today.bb_high)} <small>/ 100 · estrés ${int(today.stress_avg)}</small></div><div class="spark" id="sBb"></div></div>
    </div><a class="more" href="#/salud">Ver salud →</a>`;
  return () => {
    const t = theme();
    sparkline($("#sSleep", card), H.map((x) => x.sleep_s && +(x.sleep_s / 3600).toFixed(2)), t.violet);
    sparkline($("#sHrv", card), H.map((x) => x.hrv_night), t.good);
    sparkline($("#sRhr", card), H.map((x) => x.rhr), t.bad);
    sparkline($("#sBb", card), H.map((x) => x.bb_high), t.blue);
  };
}

function wLast(card, d) {
  const a = d.last;
  if (!a) { card.innerHTML = `<h3>Última carrera</h3><div class="muted">Sin carreras todavía.</div>`; return; }
  card.innerHTML = `
    <h3>Última carrera <span class="tag">${fdate(a.date)}</span></h3>
    <a href="#/carrera/${a.id}"><div class="mid" style="margin-bottom:6px">${esc(a.name)}</div></a>
    <div class="kpis" style="margin-top:6px">
      <div class="kpi"><div class="v num">${km(a.distance_m)} km</div><div class="l">Distancia</div></div>
      <div class="kpi"><div class="v num">${dur(a.moving_s)}</div><div class="l">Tiempo</div></div>
      <div class="kpi"><div class="v num">${pace(paceOf(a))}</div><div class="l">Ritmo /km</div></div>
      <div class="kpi"><div class="v num">${int(a.avg_hr)}</div><div class="l">FC media</div></div>
    </div>
    ${d.last_track ? `<div class="map" id="mLast"></div>` : `<div class="muted" style="margin-top:12px;font-size:13px">${a.fit_status === "pending" ? "El recorrido se descargará en la próxima sincronización." : "Sin recorrido GPS."}</div>`}`;
  return () => d.last_track && map($("#mLast", card), d.last_track, { zoom: false });
}

function wRecords(card, d) {
  const rows = d.records.filter((r) => r.best);
  card.innerHTML = `
    <h3>Récords personales</h3>
    ${rows.length ? `<div class="rec-list">${rows.filter((r) => [1000, 5000, 10000, 21097.5, 42195].includes(r.distance)).map((r) => `
      <a class="rec-row" href="#/carrera/${r.best.id}">
        <span>${r.label}</span>
        <span class="faint" style="font-size:12px">${fdateShort(r.best.date)} ${new Date(r.best.date).getFullYear()}</span>
        <span class="t num">${dur(r.best.time_s)}</span>
      </a>`).join("")}</div>
      <div class="muted" style="font-size:12px;margin-top:8px">Mejor del año: ${rows.filter((r) => r.best_year && [5000, 10000].includes(r.distance)).map((r) => `${r.label} ${dur(r.best_year.time_s)}`).join(" · ") || "–"}</div>`
    : `<div class="muted">Los récords se calculan a partir del detalle de cada carrera.</div>`}
    <a class="more" href="#/records">Ver todos →</a>`;
}

function wPredictions(card, d) {
  const s = d.snapshot || {};
  const items = [["5 km", s.race_5k, 5], ["10 km", s.race_10k, 10], ["Media", s.race_hm, 21.0975], ["Maratón", s.race_m, 42.195]];
  card.innerHTML = `<h3>Predicciones de carrera <span class="tag">Garmin</span></h3>
    ${s.race_5k ? `<div class="rec-list">${items.map(([l, v, k]) => `<div class="rec-row"><span>${l}</span><span class="faint num" style="font-size:12px">${pace(v / k)} /km</span><span class="t num">${dur(v)}</span></div>`).join("")}</div>`
    : `<div class="muted">Garmin todavía no ha enviado predicciones.</div>`}`;
}

function wWeeksChart(card, d) {
  card.innerHTML = `<h3>Kilómetros por semana <span class="tag">últimas 12</span></h3><div class="chart" id="cWeeks" style="height:200px"></div>`;
  return () => {
    const t = theme(), goal = d.week.goal_km;
    chart($("#cWeeks", card), {
      xAxis: { type: "category", data: d.weeks.map((w) => fdateShort(w.week)) },
      yAxis: { type: "value" },
      tooltip: { formatter: (ps) => `Semana del ${ps[0].axisValue}<br><b>${nf1.format(ps[0].value)} km</b> · ${d.weeks[ps[0].dataIndex].runs} carreras` },
      series: [{ type: "bar", data: d.weeks.map((w, i) => ({ value: w.km, itemStyle: { color: i === d.weeks.length - 1 ? t.accent : t.accent + "88", borderRadius: [5, 5, 0, 0] } })),
        markLine: goal ? { symbol: "none", silent: true, lineStyle: { color: t.faint, type: "dashed" }, label: { color: t.text, position: "insideEndTop", formatter: `objetivo ${goal} km` }, data: [{ yAxis: goal }] } : undefined }],
    });
  };
}

// ================================================================ CARRERAS
const listState = { q: "", year: "", sport: "", min_km: "", max_km: "", sort: "date", order: "desc", page: 1 };
route("carreras", async (view) => {
  const qs = new URLSearchParams(Object.entries(listState).filter(([, v]) => v !== "" && v != null)).toString();
  const data = await api("/api/activities?" + qs);
  const pages = Math.max(1, Math.ceil(data.total / 50));
  const maxPace = Math.max(...data.items.map(paceOf).filter(Boolean), 1);
  const th = (key, label, cls = "") => `<th data-sort="${key}" class="${cls} ${listState.sort === key ? "sorted" : ""}">${label}${listState.sort === key ? (listState.order === "desc" ? " ↓" : " ↑") : ""}</th>`;
  view.innerHTML = `
    <div class="page-head"><div><h1>Carreras</h1><div class="sub">${int(data.total)} carreras</div></div></div>
    <div class="filters">
      <input type="search" id="fq" placeholder="Buscar por nombre" value="${esc(listState.q)}">
      <select id="fyear"><option value="">Todos los años</option>${data.years.map((y) => `<option ${y === listState.year ? "selected" : ""}>${y}</option>`).join("")}</select>
      <select id="fsport"><option value="">Todos los tipos</option>${data.sports.map((s) => `<option value="${s}" ${s === listState.sport ? "selected" : ""}>${sportName(s)}</option>`).join("")}</select>
      <input type="number" id="fmin" placeholder="km mín" min="0" step="1" value="${esc(listState.min_km)}">
      <input type="number" id="fmax" placeholder="km máx" min="0" step="1" value="${esc(listState.max_km)}">
    </div>
    <div class="table-wrap"><table>
      <thead><tr>${th("date", "Carrera", "l")}<th class="l">Tipo</th>${th("distance", "Distancia")}${th("time", "Tiempo")}${th("pace", "Ritmo", "l")}${th("hr", "FC media")}${th("elev", "Desnivel")}${th("load", "Carga")}</tr></thead>
      <tbody>${data.items.map((a) => `
        <tr class="link" data-id="${a.id}">
          <td><span class="name">${esc(a.name)}</span><span class="date">${fdate(a.date)} · ${(a.start_local || "").slice(11, 16)}</span></td>
          <td class="l"><span class="tag">${sportName(a.sport)}</span></td>
          <td class="num">${km(a.distance_m)} km</td>
          <td class="num">${dur(a.moving_s)}</td>
          <td class="l num">${pace(paceOf(a))} /km <span class="pace-bar" style="width:${Math.round((maxPace / (paceOf(a) || maxPace)) * 50 - 25)}px"></span></td>
          <td class="num">${int(a.avg_hr)}</td>
          <td class="num">${int(a.elev_gain)} m</td>
          <td class="num">${int(a.training_load)}</td>
        </tr>`).join("") || `<tr><td colspan="8" class="empty">No hay carreras con estos filtros.</td></tr>`}</tbody>
    </table></div>
    <div class="pager"><button class="btn small" id="prev" ${listState.page <= 1 ? "disabled" : ""}>← Anterior</button>
      <span>Página ${listState.page} de ${pages}</span>
      <button class="btn small" id="next" ${listState.page >= pages ? "disabled" : ""}>Siguiente →</button></div>`;
  const reload = () => rerender();
  let deb;
  $("#fq").addEventListener("input", (e) => { clearTimeout(deb); deb = setTimeout(() => { listState.q = e.target.value; listState.page = 1; reload().then(() => { const i = $("#fq"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 350); });
  [["#fyear", "year"], ["#fsport", "sport"], ["#fmin", "min_km"], ["#fmax", "max_km"]].forEach(([s, k]) =>
    $(s).addEventListener("change", (e) => { listState[k] = e.target.value; listState.page = 1; reload(); }));
  $$("th[data-sort]").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.sort;
    if (listState.sort === k) listState.order = listState.order === "desc" ? "asc" : "desc";
    else { listState.sort = k; listState.order = k === "pace" ? "asc" : "desc"; }
    reload();
  }));
  $("#prev").onclick = () => { listState.page--; reload(); };
  $("#next").onclick = () => { listState.page++; reload(); };
  $$("tr.link").forEach((tr) => tr.addEventListener("click", () => (location.hash = `#/carrera/${tr.dataset.id}`)));
});

// ================================================================ DETALLE
route("carrera", async (view, id) => {
  const d = await api(`/api/activities/${id}`);
  const a = d.activity, s = d.stream;
  const prs = d.efforts.filter((e) => e.is_pr);
  view.innerHTML = `
    <div class="page-head">
      <div><a class="muted" href="#/carreras">← Carreras</a><h1>${esc(a.name)}</h1>
      <div class="sub">${fdate(a.date)} · ${(a.start_local || "").slice(11, 16)} · <span class="tag">${sportName(a.sport)}</span>
      ${prs.length ? ` <span class="tag accent">🏅 ${prs.length} récord${prs.length > 1 ? "s" : ""}</span>` : ""}</div></div>
    </div>
    <div class="card"><div class="detail-head">
      <div class="kpi"><div class="v num">${km(a.distance_m)} km</div><div class="l">Distancia</div></div>
      <div class="kpi"><div class="v num">${dur(a.moving_s)}</div><div class="l">Tiempo en movimiento</div></div>
      <div class="kpi"><div class="v num">${pace(paceOf(a))}</div><div class="l">Ritmo medio /km</div></div>
      <div class="kpi"><div class="v num">${int(a.avg_hr)} <small class="muted">/ ${int(a.max_hr)}</small></div><div class="l">FC media / máx</div></div>
      <div class="kpi"><div class="v num">${int(a.elev_gain)} m</div><div class="l">Desnivel +</div></div>
      <div class="kpi"><div class="v num">${int(a.cadence)}</div><div class="l">Cadencia ppm</div></div>
      <div class="kpi"><div class="v num">${int(a.training_load)}</div><div class="l">Carga</div></div>
      <div class="kpi"><div class="v num">${a.aerobic_te ? nf1.format(a.aerobic_te) : "–"} / ${a.anaerobic_te ? nf1.format(a.anaerobic_te) : "–"}</div><div class="l">Efecto aeróbico / anaeróbico</div></div>
      <div class="kpi"><div class="v num">${int(a.calories)}</div><div class="l">Calorías</div></div>
    </div></div>
    ${s ? `
    <div class="two-col">
      <div class="card map-card">${s.lat && s.lat.some(Boolean) ? `<div class="map tall" id="mDet"></div>` : `<div class="empty">Sin recorrido GPS (¿cinta?)</div>`}</div>
      <div class="card"><h3>Mejores esfuerzos</h3>
        ${d.efforts.length ? `<div class="rec-list">${d.efforts.map((e) => `<div class="rec-row"><span>${labelFor(e.distance_m)}</span><span class="faint num" style="font-size:12px">${pace(e.time_s / (e.distance_m / 1000))} /km</span><span class="t num ${e.is_pr ? "pr" : ""}">${e.is_pr ? "🏅 " : ""}${dur(e.time_s)}</span></div>`).join("")}</div>` : `<div class="muted">Carrera demasiado corta.</div>`}
        ${d.zones ? `<h3 style="margin-top:20px">Tiempo por zonas de FC</h3><div class="zones" id="zones"></div>` : ""}
      </div>
    </div>
    <div class="card" style="margin-top:16px"><h3>Ritmo, frecuencia cardiaca y altitud</h3><div class="chart xl" id="cStreams"></div></div>
    <div class="card" style="margin-top:16px"><h3>Parciales por kilómetro</h3><div class="table-wrap" style="border:0"><table>
      <thead><tr><th>Km</th><th class="l">Ritmo</th><th>Tiempo</th><th>FC</th><th>Cadencia</th><th>Desnivel</th></tr></thead>
      <tbody>${splitsRows(d.splits)}</tbody></table></div></div>`
    : `<div class="card empty" style="margin-top:16px">${a.fit_status === "pending" ? "El detalle (recorrido, gráficas y parciales) se descargará en la próxima sincronización." : "No hay detalle disponible para esta actividad. Puedes importar su archivo .FIT desde Ajustes."}</div>`}`;
  if (!s) return;
  if (s.lat && s.lat.some(Boolean)) map($("#mDet"), s.lat.map((la, i) => [la, s.lon[i]]).filter((p) => p[0] && p[1]), { zoom: true });
  if (d.zones) renderZones($("#zones"), d.zones);
  streamsChart($("#cStreams"), s);
});

function labelFor(dist) {
  return { 400: "400 m", 1000: "1 km", 1609.344: "1 milla", 5000: "5 km", 10000: "10 km", 15000: "15 km", 21097.5: "Media maratón", 42195: "Maratón" }[dist] || `${dist} m`;
}
function splitsRows(splits) {
  const paces = splits.filter((x) => x.dist >= 900).map((x) => x.pace);
  const fast = Math.min(...paces), slow = Math.max(...paces);
  return splits.map((x) => {
    const w = slow > fast ? 30 + 70 * (slow - x.pace) / (slow - fast) : 70;
    return `<tr><td>${x.dist < 990 ? nf1.format((x.n - 1) + x.dist / 1000) : x.n}</td>
      <td class="l num">${pace(x.pace)} <span class="pace-bar" style="width:${Math.max(6, w * 1.4)}px;${x.pace === fast ? "" : "opacity:.45"}"></span></td>
      <td class="num">${dur(x.time)}</td><td class="num">${int(x.hr)}</td><td class="num">${int(x.cad)}</td>
      <td class="num">${x.elev != null ? (Math.round(x.elev) > 0 ? "+" : "") + nf0.format(Math.round(x.elev) || 0) + " m" : "–"}</td></tr>`;
  }).join("");
}
function renderZones(el, z) {
  const total = z.seconds.reduce((a, b) => a + b, 0) || 1;
  const colors = ["#8b96a5", "#4ea4ff", "#3ccf8e", "#f5b942", "#ff5a6a"];
  const ranges = [`< ${z.limits[0]}`, `${z.limits[0]}–${z.limits[1]}`, `${z.limits[1]}–${z.limits[2]}`, `${z.limits[2]}–${z.limits[3]}`, `> ${z.limits[3]}`];
  el.innerHTML = z.seconds.map((s, i) => `<div class="zone" title="${ranges[i]} ppm"><span class="muted">Z${i + 1}</span>
    <div class="bar"><div style="width:${(s / total) * 100}%;background:${colors[i]}"></div></div><span class="num" style="text-align:right">${dur(s)}</span></div>`).join("")
    + `<div class="faint" style="font-size:11px;margin-top:4px">Zonas por % de FC máx (${z.hr_max} ppm). Ajustable en Ajustes.</div>`;
}
function smooth(arr, w) {
  return arr.map((_, i) => { const v = arr.slice(Math.max(0, i - w), i + w + 1).filter((x) => x != null); return v.length ? Math.round(v.reduce((a, b) => a + b, 0) / v.length) : null; });
}
function streamsChart(el, s) {
  const t = theme();
  const x = s.d.map((v) => +(v / 1000).toFixed(3));
  // ritmo suavizado (media móvil) para que no sea ilegible
  const raw = s.spd.map((v) => (v && v > 0.5 ? 1000 / v : null));
  const W = 7;
  const pc = raw.map((_, i) => { const w = raw.slice(Math.max(0, i - W), i + W + 1).filter(Boolean); return w.length ? Math.round(w.reduce((a, b) => a + b, 0) / w.length) : null; });
  const valid = pc.filter(Boolean).sort((a, b) => a - b);
  const pMin = valid[Math.floor(valid.length * 0.02)] || 180, pMax = valid[Math.floor(valid.length * 0.98)] || 480;
  const grids = [{ top: 10, height: "28%" }, { top: "38%", height: "28%" }, { top: "72%", height: "20%" }].map((g) => ({ left: 54, right: 14, ...g }));
  const xa = (i, show) => ({ type: "category", data: x, gridIndex: i, boundaryGap: false, axisLabel: { show, formatter: (v) => nf1.format(v) + " km", interval: Math.floor(x.length / 8) }, splitLine: { show: false } });
  chart(el, {
    grid: grids,
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    tooltip: { formatter: (ps) => `${nf1.format(ps[0].axisValue)} km<br>` + ps.map((p) => `${p.marker}${p.seriesName}: <b>${p.seriesIndex === 0 ? pace(p.value) + " /km" : p.seriesIndex === 1 ? p.value + " ppm" : nf0.format(p.value) + " m"}</b>`).join("<br>") },
    xAxis: [xa(0, false), xa(1, false), xa(2, true)],
    yAxis: [
      { type: "value", gridIndex: 0, inverse: true, min: Math.floor(pMin / 15) * 15, max: Math.ceil(pMax / 15) * 15, axisLabel: { formatter: (v) => pace(v) } },
      { type: "value", gridIndex: 1, scale: true },
      { type: "value", gridIndex: 2, scale: true },
    ],
    dataZoom: [{ type: "inside", xAxisIndex: [0, 1, 2] }],
    series: [
      { name: "Ritmo", type: "line", data: pc, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.accent, width: 1.6 }, itemStyle: { color: t.accent } },
      { name: "FC", type: "line", data: smooth(s.hr, 3), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { color: t.bad, width: 1.4 }, itemStyle: { color: t.bad } },
      { name: "Altitud", type: "line", data: s.alt, xAxisIndex: 2, yAxisIndex: 2, symbol: "none", lineStyle: { color: t.faint, width: 1 }, itemStyle: { color: t.faint }, areaStyle: { color: t.faint + "44" } },
    ],
  });
}

// ================================================================ SALUD
let healthDays = 90;
route("salud", async (view) => {
  const H = await api(`/api/health?days=${healthDays}`);
  view.innerHTML = `
    <div class="page-head"><div><h1>Salud</h1><div class="sub">Sueño, variabilidad cardiaca, pulso en reposo, Body Battery y estrés</div></div>
      <div class="seg" id="range">${[30, 90, 180, 365].map((n) => `<button data-n="${n}" class="${n === healthDays ? "on" : ""}">${n} días</button>`).join("")}</div></div>
    ${H.length ? `
    <div class="grid">
      <div class="card wide"><h3>Sueño</h3><div class="legend"><span><i style="background:var(--c-sleep-deep)"></i>Profundo</span><span><i style="background:var(--c-sleep-rem)"></i>REM</span><span><i style="background:var(--c-sleep-light)"></i>Ligero</span><span><i style="background:var(--c-sleep-awake)"></i>Despierto</span><span><i style="background:var(--accent)"></i>Puntuación</span></div><div class="chart tall" id="hSleep"></div></div>
      <div class="card"><h3>VFC nocturna</h3><div class="chart tall" id="hHrv"></div></div>
      <div class="card"><h3>FC en reposo</h3><div class="chart tall" id="hRhr"></div></div>
      <div class="card"><h3>Body Battery (mín–máx)</h3><div class="chart tall" id="hBb"></div></div>
      <div class="card"><h3>Estrés medio y disposición</h3><div class="chart tall" id="hStress"></div></div>
      <div class="card wide"><h3>Pasos</h3><div class="chart" id="hSteps"></div></div>
    </div>` : `<div class="card empty"><h2>Sin datos de salud</h2><p>Se descargan de Garmin en cada sincronización.</p></div>`}`;
  $$("#range button").forEach((b) => (b.onclick = () => { healthDays = +b.dataset.n; rerender(); }));
  if (!H.length) return;
  const t = theme(), dates = H.map((x) => x.date);
  const xa = { type: "category", data: dates, axisLabel: { formatter: (v) => fdateShort(v) } };
  const h = (s) => (s == null ? null : +(s / 3600).toFixed(2));
  chart($("#hSleep"), {
    xAxis: xa, yAxis: [{ type: "value" }, { type: "value", min: 0, max: 100, splitLine: { show: false } }],
    tooltip: { formatter: (ps) => `${fdate(ps[0].axisValue)}<br>` + ps.map((p) => `${p.marker}${p.seriesName}: <b>${p.seriesIndex < 4 ? hours(p.value * 3600) : p.value ?? "–"}</b>`).join("<br>") },
    series: [
      ["Profundo", "deep_s", "--c-sleep-deep"], ["REM", "rem_s", "--c-sleep-rem"], ["Ligero", "light_s", "--c-sleep-light"], ["Despierto", "awake_s", "--c-sleep-awake"],
    ].map(([n, k, c]) => ({ name: n, type: "bar", stack: "s", data: H.map((x) => h(x[k])), itemStyle: { color: css(c) }, barCategoryGap: "25%" }))
      .concat([{ name: "Puntuación", type: "line", yAxisIndex: 1, data: H.map((x) => x.sleep_score), symbol: "none", smooth: true, lineStyle: { color: t.accent, width: 2 }, itemStyle: { color: t.accent } }]),
  });
  chart($("#hHrv"), {
    xAxis: xa, yAxis: { type: "value", scale: true },
    series: [
      { name: "Rango normal (bajo)", type: "line", data: H.map((x) => x.hrv_low), stack: "band", symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false } },
      { name: "Rango normal", type: "line", data: H.map((x) => (x.hrv_high != null && x.hrv_low != null ? x.hrv_high - x.hrv_low : null)), stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: t.good + "22" }, tooltip: { show: false } },
      { name: "Media 7 d", type: "line", data: H.map((x) => x.hrv_weekly), symbol: "none", smooth: true, lineStyle: { color: t.good, width: 2.5 }, itemStyle: { color: t.good } },
      { name: "Noche", type: "scatter", data: H.map((x) => x.hrv_night), symbolSize: 5, itemStyle: { color: t.good + "aa" } },
    ],
  });
  chart($("#hRhr"), {
    xAxis: xa, yAxis: { type: "value", scale: true },
    series: [{ name: "FC reposo", type: "line", data: H.map((x) => x.rhr), smooth: true, symbol: "none", lineStyle: { color: t.bad, width: 2 }, itemStyle: { color: t.bad }, areaStyle: { color: t.bad + "18" } }],
  });
  chart($("#hBb"), {
    xAxis: xa, yAxis: { type: "value", min: 0, max: 100 },
    series: [
      { name: "Mínimo", type: "line", data: H.map((x) => x.bb_low), stack: "bb", symbol: "none", lineStyle: { opacity: 0 }, itemStyle: { color: t.blue } },
      { name: "Recarga", type: "line", data: H.map((x) => (x.bb_high != null && x.bb_low != null ? x.bb_high - x.bb_low : null)), stack: "bb", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: t.blue + "55" }, itemStyle: { color: t.blue } },
      { name: "Máximo", type: "line", data: H.map((x) => x.bb_high), symbol: "none", smooth: true, lineStyle: { color: t.blue, width: 2 }, itemStyle: { color: t.blue } },
    ],
  });
  chart($("#hStress"), {
    xAxis: xa, yAxis: { type: "value", min: 0, max: 100 },
    series: [
      { name: "Estrés medio", type: "line", data: H.map((x) => x.stress_avg), smooth: true, symbol: "none", lineStyle: { color: t.warn, width: 2 }, itemStyle: { color: t.warn } },
      { name: "Disposición", type: "line", data: H.map((x) => x.readiness), smooth: true, symbol: "none", lineStyle: { color: t.violet, width: 2 }, itemStyle: { color: t.violet } },
    ],
  });
  chart($("#hSteps"), {
    xAxis: xa, yAxis: { type: "value" },
    series: [{ name: "Pasos", type: "bar", data: H.map((x) => x.steps), itemStyle: { color: t.accent + "99", borderRadius: [3, 3, 0, 0] } }],
  });
});

// ================================================================ FORMA
let fitDays = 365;
route("forma", async (view) => {
  const f = await api(`/api/fitness?days=${fitDays}`);
  const last = f.series[f.series.length - 1] || {}, snap = f.snapshot || {};
  const st = trainingStatus(snap), [tl, tc] = tsbLabel(last.tsb);
  view.innerHTML = `
    <div class="page-head"><div><h1>Forma y carga</h1><div class="sub">Modelo de carga crónica (42 días), aguda (7 días) y balance</div></div>
      <div class="seg" id="range">${[90, 180, 365, 730].map((n) => `<button data-n="${n}" class="${n === fitDays ? "on" : ""}">${n < 365 ? n + " días" : n / 365 + (n === 365 ? " año" : " años")}</button>`).join("")}</div></div>
    <div class="grid">
      <div class="card"><h3>Fitness (CTL)</h3><div class="big num">${last.ctl != null ? nf0.format(last.ctl) : "–"}</div><div class="muted">Carga media de las últimas 6 semanas</div></div>
      <div class="card"><h3>Fatiga (ATL)</h3><div class="big num">${last.atl != null ? nf0.format(last.atl) : "–"}</div><div class="muted">Carga media de la última semana</div></div>
      <div class="card"><h3>Forma (TSB) <span class="tag ${tc}">${tl}</span></h3><div class="big num">${last.tsb != null ? nf0.format(last.tsb) : "–"}</div><div class="muted">Fitness menos fatiga. Para competir, entre +5 y +20.</div></div>
      <div class="card"><h3>Garmin ${st ? `<span class="tag ${st[1]}">${esc(st[0])}</span>` : ""}</h3><div class="big num">${snap.vo2max ? nf1.format(snap.vo2max) : "–"}<small>VO2max</small></div>
        <div class="muted">${snap.acute_load ? `Carga aguda ${int(snap.acute_load)} · crónica ${int(snap.chronic_load)}` : "Estado de entrenamiento según tu reloj"}</div></div>
      <div class="card wide" style="grid-column:1/-1"><h3>Evolución</h3><div class="chart xl" id="fChart"></div></div>
      <div class="card wide" style="grid-column:1/-1"><h3>VO2max</h3><div class="chart" id="vChart" style="height:220px"></div></div>
    </div>
    <p class="faint" style="font-size:12px">La carga de cada actividad es la que calcula Garmin (EPOC). Si una actividad no la tiene, se estima con el TRIMP de Banister a partir de la FC media, la FC máxima y la de reposo. Se incluyen todos los deportes, no sólo la carrera, porque todos generan fatiga.</p>`;
  $$("#range button").forEach((b) => (b.onclick = () => { fitDays = +b.dataset.n; rerender(); }));
  fitnessChart($("#fChart"), f.series, true);
  const t = theme();
  chart($("#vChart"), {
    xAxis: { type: "category", data: f.vo2.map((x) => x.date), axisLabel: { formatter: (v) => fdateShort(v) + " " + v.slice(2, 4) } },
    yAxis: { type: "value", scale: true },
    series: [{ name: "VO2max", type: "line", step: "end", data: f.vo2.map((x) => x.vo2max), symbol: "none", lineStyle: { color: t.accent, width: 2 }, itemStyle: { color: t.accent }, areaStyle: { color: t.accent + "18" } }],
  });
});

// ================================================================ RÉCORDS
route("records", async (view) => {
  const R = await api("/api/records");
  view.innerHTML = `
    <div class="page-head"><div><h1>Récords personales</h1><div class="sub">Mejores tiempos dentro de cualquier carrera, calculados con el detalle segundo a segundo</div></div></div>
    <div class="grid">${R.map((r, i) => `
      <div class="card"><h3>${r.label} ${r.best_year ? `<span class="tag">${new Date().getFullYear()}: ${dur(r.best_year.time_s)}</span>` : ""}</h3>
        ${r.top.length ? `
        <a href="#/carrera/${r.top[0].id}"><div class="big num">${dur(r.top[0].time_s)}</div></a>
        <div class="muted" style="font-size:13px">${pace(r.top[0].time_s / (r.distance / 1000))} /km · ${fdate(r.top[0].date)}</div>
        <div class="chart" id="rp${i}" style="height:110px;margin:10px 0"></div>
        <div class="rec-list">${r.top.slice(1).map((x, j) => `<a class="rec-row" href="#/carrera/${x.id}"><span class="muted">${j + 2}. ${esc(x.name)}</span><span class="faint" style="font-size:12px">${fdateShort(x.date)} ${x.date.slice(0, 4)}</span><span class="t num" style="font-size:14px">${dur(x.time_s)}</span></a>`).join("")}</div>`
        : `<div class="muted">Aún no has corrido esta distancia.</div>`}
      </div>`).join("")}</div>`;
  const t = theme();
  R.forEach((r, i) => {
    if (r.progression.length < 1) return;
    chart($(`#rp${i}`), {
      grid: { left: 4, right: 4, top: 6, bottom: 2, containLabel: true },
      tooltip: { formatter: (ps) => `${fdate(ps[0].axisValue)}<br><b>${dur(ps[0].value)}</b>` },
      xAxis: { type: "category", data: r.progression.map((p) => p.date), axisLabel: { show: false } },
      yAxis: { type: "value", scale: true, inverse: true, axisLabel: { formatter: (v) => dur(v), fontSize: 10 } },
      series: [{ type: "line", step: "end", data: r.progression.map((p) => p.time_s), symbolSize: 6, lineStyle: { color: t.accent }, itemStyle: { color: t.accent } }],
    });
  });
});

// ================================================================ ESTADÍSTICAS
let statsGroup = "month";
route("stats", async (view) => {
  const S = await api(`/api/stats?group=${statsGroup}`);
  const T = S.totals || {};
  const P = S.periods.slice(statsGroup === "week" ? -52 : statsGroup === "month" ? -36 : -20);
  const label = (p) => statsGroup === "month" ? `${MONTHS[+p.slice(5, 7) - 1]} ${p.slice(2, 4)}` : statsGroup === "week" ? fdateShort(p) : p;
  view.innerHTML = `
    <div class="page-head"><div><h1>Estadísticas</h1><div class="sub">Desde ${T.first ? fdate(T.first) : "–"}</div></div>
      <div class="seg" id="grp">${[["week", "Semanas"], ["month", "Meses"], ["year", "Años"]].map(([k, l]) => `<button data-g="${k}" class="${k === statsGroup ? "on" : ""}">${l}</button>`).join("")}</div></div>
    <div class="grid">
      <div class="card"><h3>Total</h3><div class="big num">${km(T.dist)}<small>km</small></div><div class="muted">${int(T.n)} carreras · ${hours(T.secs)} · ${int(T.elev)} m+</div></div>
      <div class="card"><h3>Ritmo medio histórico</h3><div class="big num">${pace(T.dist ? T.secs / (T.dist / 1000) : null)}<small>/km</small></div><div class="muted">Distancia media ${T.n ? km(T.dist / T.n) : "–"} km por carrera</div></div>
      <div class="card wide" style="grid-column:1/-1"><h3>Volumen y ritmo</h3><div class="chart xl" id="sVol"></div></div>
      <div class="card"><h3>¿Qué días corres?</h3><div class="chart" id="sWd" style="height:220px"></div></div>
      <div class="card"><h3>Distancias</h3><div class="chart" id="sHist" style="height:220px"></div></div>
    </div>
    <div class="section-title">Detalle por periodo</div>
    <div class="table-wrap"><table><thead><tr><th>Periodo</th><th>Carreras</th><th>Distancia</th><th>Tiempo</th><th>Ritmo</th><th>Desnivel</th><th>Más larga</th></tr></thead>
      <tbody>${[...S.periods].reverse().map((p) => `<tr><td>${label(p.period)}</td><td class="num">${p.n}</td><td class="num">${km(p.dist)} km</td><td class="num">${hours(p.secs)}</td><td class="num">${pace(p.pace)}</td><td class="num">${int(p.elev)} m</td><td class="num">${km(p.longest)} km</td></tr>`).join("")}</tbody></table></div>`;
  $$("#grp button").forEach((b) => (b.onclick = () => { statsGroup = b.dataset.g; rerender(); }));
  const t = theme();
  chart($("#sVol"), {
    legend: { top: 0, textStyle: { color: t.text } }, grid: { top: 34 },
    xAxis: { type: "category", data: P.map((p) => label(p.period)) },
    yAxis: [{ type: "value" }, { type: "value", inverse: true, scale: true, axisLabel: { formatter: (v) => pace(v) }, splitLine: { show: false } }],
    tooltip: { formatter: (ps) => `${ps[0].axisValue}<br>` + ps.map((p) => `${p.marker}${p.seriesName}: <b>${p.seriesIndex === 0 ? nf1.format(p.value) + " km" : pace(p.value) + " /km"}</b>`).join("<br>") },
    series: [
      { name: "Distancia", type: "bar", data: P.map((p) => +(p.dist / 1000).toFixed(1)), itemStyle: { color: t.accent + "cc", borderRadius: [4, 4, 0, 0] } },
      { name: "Ritmo medio", type: "line", yAxisIndex: 1, data: P.map((p) => p.pace && Math.round(p.pace)), smooth: true, symbol: "circle", symbolSize: 5, lineStyle: { color: t.blue }, itemStyle: { color: t.blue } },
    ],
  });
  const wdOrder = [1, 2, 3, 4, 5, 6, 0];
  const wd = Object.fromEntries(S.weekday.map((x) => [x.wd, x]));
  chart($("#sWd"), {
    xAxis: { type: "category", data: wdOrder.map((i) => WEEKDAYS[i]) }, yAxis: { type: "value" },
    tooltip: { formatter: (ps) => `${ps[0].axisValue}: <b>${ps[0].value}</b> carreras` },
    series: [{ type: "bar", data: wdOrder.map((i) => (wd[i] ? wd[i].n : 0)), itemStyle: { color: t.blue + "cc", borderRadius: [4, 4, 0, 0] } }],
  });
  const order = ["<5 km", "5-10 km", "10-15 km", "15-21 km", "21+ km"];
  const hist = Object.fromEntries(S.dist_hist.map((x) => [x.bucket, x.n]));
  chart($("#sHist"), {
    xAxis: { type: "category", data: order }, yAxis: { type: "value" },
    tooltip: { formatter: (ps) => `${ps[0].axisValue}: <b>${ps[0].value}</b> carreras` },
    series: [{ type: "bar", data: order.map((k) => hist[k] || 0), itemStyle: { color: t.violet + "cc", borderRadius: [4, 4, 0, 0] } }],
  });
});

// ================================================================ AJUSTES
route("ajustes", async (view) => {
  const [st, set, log, sessions] = await Promise.all([api("/api/status"), api("/api/settings"), api("/api/sync/log"), api("/api/account/sessions")]);
  view.innerHTML = `
    <div class="page-head"><div><h1>Ajustes</h1><div class="sub">Modo Guerrero v${esc(st.version)}</div></div></div>
    <div class="grid">
      <div class="card"><h3>Cuenta de Garmin ${st.connected ? `<span class="tag good">Conectada</span>` : `<span class="tag bad">Sin conectar</span>`}</h3>
        <div id="garminBox"></div>
      </div>
      <div class="card"><h3>Apariencia</h3>
        <label class="field">Tema</label>
        <div class="seg" id="themeSeg" style="margin-top:6px">${THEMES.map(([k, l]) => `<button data-theme="${k}" class="${(set.theme || "auto") === k ? "on" : ""}">${l}</button>`).join("")}</div>
        <div class="faint" style="font-size:12px;margin-top:6px">Automático sigue el modo claro u oscuro del dispositivo. Negro ahorra batería en pantallas OLED.</div>
        <label class="field" style="margin-top:16px">Color principal</label>
        <div class="swatches" id="accentSw">${ACCENTS.map(([c, l]) => `<button class="swatch ${(set.accent || "#ff6b2c").toLowerCase() === c ? "on" : ""}" data-accent="${c}" title="${l}" aria-label="${l}" style="background:${c}"></button>`).join("")}
          <label class="swatch" title="Personalizado" style="background:conic-gradient(red,yellow,lime,cyan,blue,magenta,red);position:relative;overflow:hidden">
            <input type="color" id="accentCustom" value="${esc(set.accent || "#ff6b2c")}" style="opacity:0;position:absolute;inset:0;width:100%;height:100%;cursor:pointer"></label>
        </div>
      </div>
      <div class="card"><h3>Tu cuenta ${ME && ME.is_admin ? `<span class="tag accent">Administrador</span>` : ""}</h3>
        <p>Has iniciado sesión como <b>${esc(ME ? ME.username : "")}</b>.</p>
        <div class="row"><button class="btn" id="logoutBtn">Cerrar sesión</button><button class="btn ghost" id="pwToggle">Cambiar contraseña</button></div>
        <form id="pwForm" class="form-grid" style="grid-template-columns:1fr;margin-top:14px" hidden>
          <input type="text" autocomplete="username" value="${esc(ME ? ME.username : "")}" hidden>
          <label class="field">Contraseña actual<input type="password" id="pwCur" required autocomplete="current-password"></label>
          <label class="field">Nueva contraseña<input type="password" id="pwNew" required minlength="10" autocomplete="new-password"></label>
          <label class="field">Repite la nueva<input type="password" id="pwNew2" required minlength="10" autocomplete="new-password"></label>
          <div class="row"><button class="btn primary">Guardar contraseña</button></div>
          <div class="faint" style="font-size:12px">Al cambiarla se cierra la sesión en el resto de dispositivos.</div>
          <div id="pwMsg"></div>
        </form>
        <h3 style="margin-top:20px">Dispositivos con sesión abierta</h3>
        <div class="rec-list">${sessions.map((x) => `
          <div class="rec-row" style="grid-template-columns:1fr auto">
            <span>${esc(deviceName(x.user_agent))} ${x.current ? `<span class="tag good">Este dispositivo</span>` : ""}<br>
              <span class="faint" style="font-size:12px">Último uso ${esc(timeAgo(x.last_seen))} · ${x.remember ? "recordado hasta el " + fdateShort(x.expires) : "sesión corta"}</span></span>
            ${x.current ? "" : `<button class="btn small ghost" data-revoke="${esc(x.id)}">Cerrar</button>`}
          </div>`).join("")}</div>
        ${sessions.length > 1 ? `<div class="row" style="margin-top:10px"><button class="btn small" id="revokeOthers">Cerrar sesión en los demás</button></div>` : ""}
      </div>
      <div class="card"><h3>Sincronización</h3>
        <div class="muted" style="font-size:13px;margin-bottom:12px">
          ${int(st.counts.runs)} carreras de ${int(st.counts.total)} actividades · ${int(st.health_days)} días de salud<br>
          ${st.counts.pending_fit ? `${int(st.counts.pending_fit)} carreras pendientes de descargar el detalle (se hace poco a poco para no saturar a Garmin)<br>` : ""}
          ${st.sync.next_run ? `Próxima: ${esc(st.sync.next_run.replace("T", " "))}` : ""}
        </div>
        <div class="form-grid">
          <label class="field">Cada (minutos)<input type="number" min="15" step="5" id="s_int" value="${set.sync_interval_min}"></label>
          <label class="field">Detalles por sincronización<input type="number" min="5" max="200" id="s_fit" value="${set.fit_per_run}"></label>
          <label class="field">Días de salud en la 1ª carga<input type="number" min="7" max="3650" id="s_back" value="${set.health_backfill_days}"></label>
        </div>
        <div class="row" style="margin-top:14px"><button class="btn primary" id="saveSync">Guardar</button><button class="btn" id="syncNow" ${st.connected ? "" : "disabled"}>Sincronizar ahora</button></div>
      </div>
      <div class="card"><h3>Objetivos</h3>
        <div class="form-grid">
          <label class="field">Semanal (km)<input type="number" min="0" id="g_w" value="${set.weekly_goal_km ?? ""}"></label>
          <label class="field">Mensual (km)<input type="number" min="0" id="g_m" value="${set.monthly_goal_km ?? ""}"></label>
          <label class="field">Anual (km)<input type="number" min="0" id="g_y" value="${set.yearly_goal_km ?? ""}"></label>
        </div>
        <h3 style="margin-top:20px">Frecuencia cardiaca</h3>
        <div class="form-grid">
          <label class="field">FC máxima<input type="number" min="120" max="230" id="h_max" placeholder="automática" value="${set.hr_max ?? ""}"></label>
          <label class="field">FC en reposo<input type="number" min="30" max="100" id="h_rest" placeholder="automática" value="${set.hr_rest ?? ""}"></label>
        </div>
        <div class="faint" style="font-size:12px;margin-top:6px">Vacío = se calcula sola (FC máxima registrada y media de reposo de 30 días).</div>
        <div class="row" style="margin-top:14px"><button class="btn primary" id="saveGoals">Guardar</button></div>
      </div>
      <div class="card"><h3>Importar archivos .FIT</h3>
        <div class="drop" id="drop">Arrastra aquí archivos .fit o .zip (del export de Garmin), o haz clic para elegirlos<input type="file" id="file" multiple accept=".fit,.zip" hidden></div>
        <div class="muted" style="font-size:12px;margin-top:8px">Si la actividad ya existe, sólo se le añade el detalle. Útil como plan B si Garmin falla.</div>
        <div id="upRes" style="margin-top:8px;font-size:13px"></div>
      </div>
      <div class="card wide" style="grid-column:1/-1"><h3>Historial de sincronizaciones</h3>
        <div class="table-wrap log" style="border:0"><table><thead><tr><th class="l">Inicio</th><th class="l">Estado</th><th class="l">Resultado</th></tr></thead>
        <tbody>${log.map((l) => `<tr><td class="l num">${esc((l.started || "").replace("T", " "))}</td><td class="l">${{ ok: '<span class="tag good">Correcta</span>', running: '<span class="tag accent">En curso</span>', auth: '<span class="tag bad">Sesión</span>', rate: '<span class="tag warn">Límite</span>' }[l.status] || '<span class="tag bad">Error</span>'}</td><td class="l">${esc(l.message || "")}</td></tr>`).join("") || `<tr><td colspan="3" class="muted">Todavía no ha habido sincronizaciones.</td></tr>`}</tbody></table></div>
      </div>
    </div>`;
  garminBox($("#garminBox"), st);
  $("#logoutBtn").onclick = logout;
  const saveAppearance = async (theme, accent) => {
    applyTheme(theme, accent);
    await api("/api/settings", { method: "PUT", body: { theme, accent } });
    rerender();
  };
  $$("#themeSeg button").forEach((b) => (b.onclick = () => saveAppearance(b.dataset.theme, set.accent)));
  $$("#accentSw [data-accent]").forEach((b) => (b.onclick = () => saveAppearance(set.theme, b.dataset.accent)));
  $("#accentCustom").onchange = (e) => saveAppearance(set.theme, e.target.value);
  $("#pwToggle").onclick = () => { const f = $("#pwForm"); f.hidden = !f.hidden; if (!f.hidden) $("#pwCur").focus(); };
  $("#pwForm").onsubmit = async (e) => {
    e.preventDefault();
    const m = $("#pwMsg");
    if ($("#pwNew").value !== $("#pwNew2").value) { m.innerHTML = `<p class="tag bad">Las contraseñas nuevas no coinciden.</p>`; return; }
    try {
      await api("/api/account/password", { method: "POST", body: { current: $("#pwCur").value, new: $("#pwNew").value } });
      toast("Contraseña cambiada"); rerender();
    } catch (err) { m.innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`; }
  };
  $$("[data-revoke]").forEach((b) => (b.onclick = async () => { await api(`/api/account/sessions/${b.dataset.revoke}`, { method: "DELETE" }); rerender(); }));
  const ro = $("#revokeOthers");
  if (ro) ro.onclick = async () => { await api("/api/account/sessions/revoke-others", { method: "POST" }); toast("Sesiones cerradas"); rerender(); };
  const num = (id) => { const v = $(id).value; return v === "" ? null : +v; };
  $("#saveSync").onclick = async () => { await api("/api/settings", { method: "PUT", body: { sync_interval_min: num("#s_int") || 60, fit_per_run: num("#s_fit") || 40, health_backfill_days: num("#s_back") || 180 } }); toast("Guardado. El nuevo intervalo se aplica tras la próxima sincronización."); };
  $("#saveGoals").onclick = async () => { await api("/api/settings", { method: "PUT", body: { weekly_goal_km: num("#g_w"), monthly_goal_km: num("#g_m"), yearly_goal_km: num("#g_y"), hr_max: num("#h_max"), hr_rest: num("#h_rest") } }); toast("Guardado"); };
  $("#syncNow").onclick = async () => { try { await api("/api/sync", { method: "POST" }); toast("Sincronización iniciada"); setTimeout(refreshStatus, 800); } catch (e) { toast(e.message, true); } };
  // subida de FIT
  const drop = $("#drop"), file = $("#file");
  drop.onclick = () => file.click();
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files); };
  file.onchange = () => upload(file.files);
  async function upload(files) {
    if (!files.length) return;
    const fd = new FormData();
    [...files].forEach((f) => fd.append("files", f));
    $("#upRes").textContent = "Importando…";
    try {
      const r = await api("/api/upload", { method: "POST", body: fd });
      $("#upRes").innerHTML = r.map((f) => `${esc(f.file)}: ${f.results.map((x) => x.ok ? `<span class="tag good">${x.merged ? "detalle añadido" : "importada"}</span>` : `<span class="tag bad">${esc(x.error)}</span>`).join(" ")}`).join("<br>");
    } catch (e) { $("#upRes").innerHTML = `<span class="tag bad">${esc(e.message)}</span>`; }
  }
});

function deviceName(ua) {
  ua = ua || "";
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android" : /Mac OS X/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "Dispositivo";
  const br = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /CriOS|Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "";
  return br ? `${br} en ${os}` : os;
}

function garminBox(box, st) {
  if (st.connected) {
    box.innerHTML = `<p>Conectada como <b>${esc(st.email || "")}</b>.</p>
      <p class="muted" style="font-size:13px">Tu contraseña no se guarda: sólo un token de sesión cifrado que Garmin renueva automáticamente. Si caduca, verás un aviso y podrás reconectar aquí.</p>
      <div class="row"><button class="btn" id="reconnect">Volver a conectar</button><button class="btn ghost" id="logout">Desconectar</button></div>`;
    $("#logout", box).onclick = async () => { if (!confirm("¿Desconectar Garmin? Tus datos ya importados se conservan.")) return; await api("/api/garmin/logout", { method: "POST" }); rerender(); };
    $("#reconnect", box).onclick = () => loginForm(box, st.email);
  } else loginForm(box, st.email);
}

function loginForm(box, email) {
  box.innerHTML = `
    <form id="lf" class="form-grid" style="grid-template-columns:1fr">
      <label class="field">Correo de Garmin Connect<input type="email" id="le" required autocomplete="username" value="${esc(email || "")}"></label>
      <label class="field">Contraseña<input type="password" id="lp" required autocomplete="current-password"></label>
      <div class="row"><button class="btn primary" id="lb">Conectar</button></div>
    </form>
    <p class="faint" style="font-size:12px">La contraseña se envía a Garmin una sola vez para obtener el token de sesión y no se guarda.</p>
    <div id="lmsg"></div>`;
  $("#lf", box).onsubmit = async (e) => {
    e.preventDefault();
    const b = $("#lb", box);
    b.disabled = true; b.textContent = "Conectando…";
    try {
      const r = await api("/api/garmin/login", { method: "POST", body: { email: $("#le", box).value, password: $("#lp", box).value } });
      if (r.mfa) mfaForm(box);
      else { toast("Garmin conectado. Empieza la primera sincronización."); rerender(); }
    } catch (err) {
      $("#lmsg", box).innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`;
      b.disabled = false; b.textContent = "Conectar";
    }
  };
}

function mfaForm(box) {
  box.innerHTML = `
    <p><b>Verificación en dos pasos.</b> Garmin te ha enviado un código. Introdúcelo aquí (tienes 10 minutos).</p>
    <form id="mf" class="row">
      <input type="text" id="mc" inputmode="numeric" autocomplete="one-time-code" maxlength="10" placeholder="Código" style="width:140px;font-size:20px;letter-spacing:.2em" required>
      <button class="btn primary" id="mb">Verificar</button>
    </form><div id="mmsg" style="margin-top:8px"></div>`;
  $("#mc", box).focus();
  $("#mf", box).onsubmit = async (e) => {
    e.preventDefault();
    const b = $("#mb", box);
    b.disabled = true; b.textContent = "Verificando…";
    try {
      await api("/api/garmin/mfa", { method: "POST", body: { code: $("#mc", box).value } });
      toast("Garmin conectado. Empieza la primera sincronización.");
      rerender();
    } catch (err) {
      $("#mmsg", box).innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`;
      b.disabled = false; b.textContent = "Verificar";
      if (/caducado|correo y contraseña/i.test(err.message)) setTimeout(() => loginForm(box), 2500);
    }
  };
}

// ---------------------------------------------------------------- acceso
function showAuth(setup) {
  disposeAll();
  clearTimeout(refreshStatus._t);
  document.body.classList.add("auth-screen");
  $("#banner").hidden = true;
  const view = $("#view");
  view.innerHTML = `
    <div class="auth-wrap"><div class="card auth-card">
      <div class="auth-logo"><svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="var(--accent)"/><path d="M8 22l6-12 4 8 3-5 3 9" stroke="#fff" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg><span>Modo Guerrero</span></div>
      ${setup ? `<h2>Crea tu cuenta</h2><p class="muted">Es la primera vez que entras. Esta cuenta será la de administrador y con ella entrarás desde cualquier dispositivo.</p>`
              : `<h2>Inicia sesión</h2>`}
      <form id="af" class="form-grid" style="grid-template-columns:1fr">
        <label class="field">Usuario<input type="text" id="au" required autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" minlength="3" maxlength="40"></label>
        <label class="field">Contraseña<input type="password" id="ap" required autocomplete="${setup ? "new-password" : "current-password"}" ${setup ? 'minlength="10"' : ""}></label>
        ${setup ? `<label class="field">Repite la contraseña<input type="password" id="ap2" required autocomplete="new-password" minlength="10"></label>
                   <div class="faint" style="font-size:12px">Mínimo 10 caracteres. Una frase de varias palabras es fácil de recordar y difícil de adivinar.</div>` : ""}
        <label class="check"><input type="checkbox" id="ar" checked> Recordar este dispositivo (90 días)</label>
        <button class="btn primary" id="ab" style="justify-content:center">${setup ? "Crear cuenta y entrar" : "Entrar"}</button>
        <div id="amsg"></div>
      </form>
    </div></div>`;
  $("#au").focus();
  $("#af").onsubmit = async (e) => {
    e.preventDefault();
    const msg = $("#amsg"), b = $("#ab");
    msg.innerHTML = "";
    if (setup && $("#ap").value !== $("#ap2").value) { msg.innerHTML = `<p class="tag bad">Las contraseñas no coinciden.</p>`; return; }
    b.disabled = true;
    try {
      const r = await api(setup ? "/api/auth/setup" : "/api/auth/login", { method: "POST",
        body: { username: $("#au").value, password: $("#ap").value, remember: $("#ar").checked } });
      ME = r.user;
      enterApp();
    } catch (err) {
      msg.innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`;
      b.disabled = false;
    }
  };
}

async function enterApp() {
  AUTHED = true;
  document.body.classList.remove("auth-screen");
  try { const st = await api("/api/settings"); applyTheme(st.theme, st.accent); } catch { /* usar el local */ }
  rerender();
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* da igual */ }
  AUTHED = false; ME = null;
  showAuth(false);
}

// ---------------------------------------------------------------- arranque
(async () => {
  try {
    const me = await api("/api/auth/me");
    $("#version").textContent = "v" + me.version;
    if (me.user) { ME = me.user; enterApp(); }
    else showAuth(me.setup_required);
  } catch (e) {
    $("#view").innerHTML = `<div class="empty"><h2>No se puede conectar con la app</h2><p>${esc(e.message)}</p></div>`;
  }
})();
