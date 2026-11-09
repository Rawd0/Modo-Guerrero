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
  if (r.status === 403 && data && data.must_change) {
    showForcedChange();
    throw new Error(data.detail);
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
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === ({ carrera: "carreras", objetivo: "objetivos", plan: "objetivos" }[key] || key)));
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
  year_progress: { title: "Progresión del año", render: wYearProgress },
  shoes: { title: "Zapatillas", render: wShoes },
  next_race: { title: "Próxima carrera", render: wNextRace },
  today_session: { title: "Hoy toca", render: wToday },
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
    ${(() => { const w = lastMono(d.monotony); return w ? `<div class="row" style="font-size:12px;margin-bottom:4px"><span class="muted">Monotonía ${w.monotony != null ? nf1.format(w.monotony) : "–"} · tensión ${int(w.strain)}</span>${monoTag(w)}</div>` : ""; })()}
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

function wYearProgress(card, d) {
  const P = d.progression || { years: [] };
  card.innerHTML = `<h3>Progresión del año <span class="tag">km acumulados</span></h3><div class="muted" style="font-size:13px" id="ypInfo"></div><div class="chart" id="cYp" style="height:200px"></div>
    <a class="more" href="#/stats">Comparar todos los años →</a>`;
  if (!P.years.length) { $("#ypInfo", card).textContent = "Sin carreras todavía."; return; }
  return () => {
    const same = P.years.map((y) => ({ year: y.year, value: y.series[Math.min(P.today_doy, y.series.length) - 1] || 0 }));
    progressionChart($("#cYp", card), { metric: "distance", years: P.years, same_date: same }, $("#ypInfo", card), true);
  };
}

function wNextRace(card, d) {
  const r = d.next_race;
  if (!r) {
    card.innerHTML = `<h3>Próxima carrera</h3><div class="muted">Añade tu próxima carrera para ver la cuenta atrás, tu predicción y si llegarás en forma.</div><a class="more" href="#/objetivos">Añadir carrera →</a>`;
    return;
  }
  const p = r.prediction || {}, [lo, hi] = r.tsb_window || [5, 15];
  const tsbOk = r.race_tsb != null && r.race_tsb >= lo && r.race_tsb <= hi;
  card.innerHTML = `<h3>Próxima carrera <span class="tag ${r.priority === "A" ? "accent" : ""}">Prioridad ${r.priority}</span></h3>
    <a href="#/objetivo/${r.id}"><div class="mid">${esc(r.name)}</div></a>
    <div class="muted" style="font-size:13px">${fdate(r.date)} · ${raceDist(r)}</div>
    <div class="row" style="align-items:baseline;margin-top:10px"><span class="big num">${r.days_left}</span><span class="muted">${r.days_left === 1 ? "día" : "días"}</span></div>
    <div class="kpis">
      <div class="kpi"><div class="v num">${r.goal_time_s ? dur(r.goal_time_s) : "–"}</div><div class="l">Objetivo</div></div>
      <div class="kpi"><div class="v num">${p.estimate ? dur(p.estimate) : "–"}</div><div class="l">Predicción hoy</div></div>
      <div class="kpi"><div class="v num">${r.race_tsb != null ? tsbFmt(r.race_tsb) : "–"}</div><div class="l">Forma prevista <span class="tag ${tsbOk ? "good" : "warn"}" style="font-size:10px;padding:1px 5px">${tsbOk ? "en rango" : "fuera de rango"}</span></div></div>
    </div>
    <a class="more" href="#/objetivo/${r.id}">Ver preparación →</a>`;
}

function wToday(card, d) {
  const T = d.today_session;
  if (!T) {
    card.innerHTML = `<h3>Hoy toca</h3><div class="muted">Crea un plan de entrenamiento para tu próxima carrera y aquí verás la sesión del día.</div><a class="more" href="#/objetivos">Ir a objetivos →</a>`;
    return;
  }
  const s = T.session;
  const todayIso = isoToday();
  const isToday = s && s.date === todayIso;
  const dots = WEEK_ORDER.map((i) => {
    const day = T.week.find((x) => new Date(x.date + "T12:00:00").getDay() === i);
    const cls = !day ? "rest" : day.status === "done" ? "done" : day.status === "missed" ? "missed" : day.status === "skipped" ? "skipped" : day.date === todayIso ? "today" : "";
    return `<span class="wkdot ${cls}" title="${WEEKDAYS[i]}${day ? " · " + SESSION_TYPES[day.type].label : " · descanso"}">${WEEKDAYS[i][0].toUpperCase()}</span>`;
  }).join("");
  card.innerHTML = `<h3>${isToday ? "Hoy toca" : "Próxima sesión"} ${s && s.status === "done" ? `<span class="tag good">Hecha</span>` : ""}</h3>
    ${s ? `<div class="row" style="gap:8px;align-items:center">${typeTag(s.type)}<span class="mid">${s.type === "race" ? esc(T.race_name) : `${nf1.format(s.distance_km).replace(",0", "")} km`}</span></div>
      ${isToday ? "" : `<div class="muted" style="font-size:13px;margin-top:2px">${fdate(s.date, false)}</div>`}
      <p style="margin:8px 0 4px;font-size:14px">${esc(s.description)}</p>` : `<div class="muted">No quedan sesiones pendientes.</div>`}
    <div class="wkdots">${dots}</div>
    <a class="more" href="#/plan/${T.race_id}">Ver plan · ${esc(T.race_name)} →</a>`;
}

function wShoes(card, d) {
  const S = d.shoes || [];
  const colors = { ok: "var(--accent)", soon: "var(--warn)", replace: "var(--bad)" };
  card.innerHTML = `<h3>Zapatillas ${S.some((x) => x.status === "replace") ? `<span class="tag bad">Toca cambiar</span>` : S.some((x) => x.status === "soon") ? `<span class="tag warn">Pronto</span>` : ""}</h3>
    ${S.length ? `<div class="rec-list">${S.slice(0, 4).map((x) => `
      <div style="padding:6px 0">
        <div class="row" style="justify-content:space-between"><span><b>${esc(x.name)}</b> ${x.is_default ? `<span class="tag">Por defecto</span>` : ""}</span><span class="num">${nf0.format(x.km)} / ${nf0.format(x.limit_km)} km</span></div>
        <div class="progress" style="margin:6px 0 0"><div style="width:${Math.min(100, x.pct || 0)}%;background:${colors[x.status] || "var(--accent)"}"></div></div>
      </div>`).join("")}</div>`
    : `<div class="muted">Añade tus zapatillas para llevar la cuenta de sus kilómetros y saber cuándo cambiarlas.</div>`}
    <a class="more" href="#/zapatillas">${S.length ? "Gestionar →" : "Añadir zapatillas →"}</a>`;
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
      <thead><tr>${th("date", "Carrera", "l")}<th class="l">Tipo</th>${th("distance", "Distancia")}${th("time", "Tiempo")}${th("pace", "Ritmo", "l")}${th("gap", "GAP")}${th("hr", "FC media")}${th("elev", "Desnivel")}${th("load", "Carga")}</tr></thead>
      <tbody>${data.items.map((a) => `
        <tr class="link" data-id="${a.id}">
          <td><span class="name">${esc(a.name)}</span><span class="date">${fdate(a.date)} · ${(a.start_local || "").slice(11, 16)}</span></td>
          <td class="l"><span class="tag">${sportName(a.sport)}</span></td>
          <td class="num">${km(a.distance_m)} km</td>
          <td class="num">${dur(a.moving_s)}</td>
          <td class="l num">${pace(paceOf(a))} /km <span class="pace-bar" style="width:${Math.round((maxPace / (paceOf(a) || maxPace)) * 50 - 25)}px"></span></td>
          <td class="num muted">${a.gap_pace ? pace(a.gap_pace) : "–"}</td>
          <td class="num">${int(a.avg_hr)}</td>
          <td class="num">${int(a.elev_gain)} m</td>
          <td class="num">${int(a.training_load)}</td>
        </tr>`).join("") || `<tr><td colspan="9" class="empty">No hay carreras con estos filtros.</td></tr>`}</tbody>
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
    else { listState.sort = k; listState.order = k === "pace" || k === "gap" ? "asc" : "desc"; }
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
      <div class="kpi" title="Ritmo equivalente en llano: cuánto habrías ido en llano con el mismo esfuerzo"><div class="v num">${a.gap_pace ? pace(a.gap_pace) : "–"}</div><div class="l">Ritmo ajustado (GAP) /km</div></div>
      <div class="kpi"><div class="v num">${int(a.avg_hr)} <small class="muted">/ ${int(a.max_hr)}</small></div><div class="l">FC media / máx</div></div>
      <div class="kpi"><div class="v num">${int(a.elev_gain)} m</div><div class="l">Desnivel +</div></div>
      <div class="kpi"><div class="v num">${int(a.cadence)}</div><div class="l">Cadencia ppm</div></div>
      <div class="kpi"><div class="v num">${int(a.training_load)}</div><div class="l">Carga</div></div>
      <div class="kpi"><div class="v num">${a.aerobic_te ? nf1.format(a.aerobic_te) : "–"} / ${a.anaerobic_te ? nf1.format(a.anaerobic_te) : "–"}</div><div class="l">Efecto aeróbico / anaeróbico</div></div>
      <div class="kpi"><div class="v num">${int(a.calories)}</div><div class="l">Calorías</div></div>
      <div class="kpi"><select id="shoeSel" style="width:100%;max-width:220px">
          <option value="">Sin zapatilla</option>
          ${d.shoes.filter((x) => !x.retired || x.id === a.shoe_id).map((x) => `<option value="${x.id}" ${x.id === a.shoe_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}
        </select><div class="l">Zapatilla${d.shoes.length ? "" : ` · <a href="#/zapatillas" style="color:var(--accent)">añadir</a>`}</div></div>
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
      <thead><tr><th>Km</th><th class="l">Ritmo</th><th title="Ritmo ajustado a la pendiente">GAP</th><th>Tiempo</th><th>FC</th><th>Cadencia</th><th>Desnivel</th></tr></thead>
      <tbody>${splitsRows(d.splits)}</tbody></table></div></div>`
    : `<div class="card empty" style="margin-top:16px">${a.fit_status === "pending" ? "El detalle (recorrido, gráficas y parciales) se descargará en la próxima sincronización." : "No hay detalle disponible para esta actividad. Puedes importar su archivo .FIT desde Ajustes."}</div>`}`;
  $("#shoeSel").onchange = async (e) => {
    try { await api(`/api/activities/${a.id}/shoe`, { method: "PUT", body: { shoe_id: e.target.value ? +e.target.value : null } }); toast("Zapatilla guardada"); }
    catch (err) { toast(err.message, true); }
  };
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
      <td class="num muted">${x.gap ? pace(x.gap) : "–"}</td>
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
  const gapRaw = (s.gap_spd || []).map((v) => (v && v > 0.5 ? 1000 / v : null));
  const gap = s.gap_spd ? gapRaw.map((_, i) => { const w = gapRaw.slice(Math.max(0, i - W), i + W + 1).filter(Boolean); return w.length ? Math.round(w.reduce((a, b) => a + b, 0) / w.length) : null; }) : null;
  const valid = pc.filter(Boolean).sort((a, b) => a - b);
  const pMin = valid[Math.floor(valid.length * 0.02)] || 180, pMax = valid[Math.floor(valid.length * 0.98)] || 480;
  const grids = [{ top: 10, height: "28%" }, { top: "38%", height: "28%" }, { top: "72%", height: "20%" }].map((g) => ({ left: 54, right: 14, ...g }));
  const xa = (i, show) => ({ type: "category", data: x, gridIndex: i, boundaryGap: false, axisLabel: { show, formatter: (v) => nf1.format(v) + " km", interval: Math.floor(x.length / 8) }, splitLine: { show: false } });
  chart(el, {
    grid: grids,
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    legend: gap ? { top: 0, right: 14, data: ["Ritmo", "GAP"], textStyle: { color: t.text, fontSize: 11 } } : undefined,
    tooltip: { formatter: (ps) => `${nf1.format(ps[0].axisValue)} km<br>` + ps.map((p) => `${p.marker}${p.seriesName}: <b>${p.seriesName === "FC" ? p.value + " ppm" : p.seriesName === "Altitud" ? nf0.format(p.value) + " m" : pace(p.value) + " /km"}</b>`).join("<br>") },
    xAxis: [xa(0, false), xa(1, false), xa(2, true)],
    yAxis: [
      { type: "value", gridIndex: 0, inverse: true, min: Math.floor(pMin / 15) * 15, max: Math.ceil(pMax / 15) * 15, axisLabel: { formatter: (v) => pace(v) } },
      { type: "value", gridIndex: 1, scale: true },
      { type: "value", gridIndex: 2, scale: true },
    ],
    dataZoom: [{ type: "inside", xAxisIndex: [0, 1, 2] }],
    series: [
      { name: "Ritmo", type: "line", data: pc, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.accent, width: 1.6 }, itemStyle: { color: t.accent } },
      ...(gap ? [{ name: "GAP", type: "line", data: gap, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.blue, width: 1.2, type: "dashed" }, itemStyle: { color: t.blue } }] : []),
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
      <div class="card wide" style="grid-column:1/-1"><h3>Monotonía y tensión semanal ${monoTag(lastMono(f.monotony))}</h3>
        <div class="row" style="gap:28px;margin-bottom:6px">${monoSummary(lastMono(f.monotony))}</div>
        <div class="chart tall" id="mChart"></div>
        <p class="faint" style="font-size:12px;margin:8px 0 0">Monotonía = carga media diaria ÷ su desviación típica en la semana: por encima de 2 indica días demasiado parecidos entre sí, sin contraste entre duros y suaves.
        Tensión = carga semanal × monotonía; se marca alta cuando supera tu propia media de las 12 semanas anteriores más 1,5 desviaciones. Mucha carga con poca variedad es cuando más riesgo hay de sobrecarga o enfermedad (Foster).</p></div>
      <div class="card wide" style="grid-column:1/-1"><h3>VO2max</h3><div class="chart" id="vChart" style="height:220px"></div></div>
    </div>
    <p class="faint" style="font-size:12px">La carga de cada actividad es la que calcula Garmin (EPOC). Si una actividad no la tiene, se estima con el TRIMP de Banister a partir de la FC media, la FC máxima y la de reposo. Se incluyen todos los deportes, no sólo la carrera, porque todos generan fatiga.</p>`;
  $$("#range button").forEach((b) => (b.onclick = () => { fitDays = +b.dataset.n; rerender(); }));
  fitnessChart($("#fChart"), f.series, true);
  monotonyChart($("#mChart"), f.monotony.weeks);
  const t = theme();
  chart($("#vChart"), {
    xAxis: { type: "category", data: f.vo2.map((x) => x.date), axisLabel: { formatter: (v) => fdateShort(v) + " " + v.slice(2, 4) } },
    yAxis: { type: "value", scale: true },
    series: [{ name: "VO2max", type: "line", step: "end", data: f.vo2.map((x) => x.vo2max), symbol: "none", lineStyle: { color: t.accent, width: 2 }, itemStyle: { color: t.accent }, areaStyle: { color: t.accent + "18" } }],
  });
});

function lastMono(m) {
  // la semana en curso puede no tener carga aún: usar la última con entrenamientos
  const ws = (m && m.weeks) || [];
  for (let i = ws.length - 1; i >= 0; i--) if (ws[i].load > 0) return ws[i];
  return null;
}
function monoTag(w) {
  if (!w) return "";
  if (w.flags.includes("strain")) return `<span class="tag bad">Tensión alta</span>`;
  if (w.flags.includes("monotony")) return `<span class="tag warn">Entrenamiento monótono</span>`;
  return `<span class="tag good">Equilibrado</span>`;
}
function monoSummary(w) {
  if (!w) return `<span class="muted">Sin carga registrada todavía.</span>`;
  return `<div class="kpi"><div class="v num">${w.monotony != null ? nf1.format(w.monotony) : "–"}</div><div class="l">Monotonía (semana del ${fdateShort(w.week)})</div></div>
    <div class="kpi"><div class="v num">${int(w.strain)}</div><div class="l">Tensión${w.strain_limit ? ` · tu límite ${int(w.strain_limit)}` : ""}</div></div>
    <div class="kpi"><div class="v num">${int(w.load)}</div><div class="l">Carga · ${w.days} días con entreno</div></div>`;
}
function monotonyChart(el, weeks) {
  const t = theme();
  return chart(el, {
    legend: { top: 0, textStyle: { color: t.text }, icon: "roundRect" }, grid: { top: 34 },
    xAxis: { type: "category", data: weeks.map((w) => fdateShort(w.week)) },
    yAxis: [{ type: "value" }, { type: "value", min: 0, max: (v) => Math.max(3, Math.ceil(v.max)), splitLine: { show: false } }],
    tooltip: { formatter: (ps) => `Semana del ${ps[0].axisValue}<br>` + ps.map((p) => `${p.marker}${p.seriesName}: <b>${p.value == null ? "–" : p.seriesName === "Monotonía" ? nf1.format(p.value) : nf0.format(p.value)}</b>`).join("<br>") },
    series: [
      { name: "Tensión", type: "bar", data: weeks.map((w) => ({ value: w.strain, itemStyle: { color: w.flags.includes("strain") ? t.bad : t.accent + "aa", borderRadius: [4, 4, 0, 0] } })), itemStyle: { color: t.accent } },
      { name: "Tu límite de tensión", type: "line", data: weeks.map((w) => w.strain_limit), symbol: "none", step: "middle", lineStyle: { color: t.bad, type: "dashed", width: 1.2 }, itemStyle: { color: t.bad } },
      { name: "Monotonía", type: "line", yAxisIndex: 1, data: weeks.map((w) => w.monotony), symbol: "circle", symbolSize: 5, lineStyle: { color: t.violet, width: 2 }, itemStyle: { color: t.violet },
        markLine: { symbol: "none", silent: true, lineStyle: { color: t.warn, type: "dotted" }, label: { color: t.text, formatter: "monotonía 2", position: "insideEndTop" }, data: [{ yAxis: 2 }] } },
    ],
  });
}

// ================================================================ RÉCORDS
route("records", async (view) => {
  const [R, PC] = await Promise.all([api("/api/records"), api("/api/pace-curve?days=90")]);
  view.innerHTML = `
    <div class="page-head"><div><h1>Récords personales</h1><div class="sub">Mejores tiempos dentro de cualquier carrera, calculados con el detalle segundo a segundo</div></div></div>
    ${PC.all.length ? `<div class="card" style="margin-bottom:16px"><h3>Curva de ritmo</h3>
      <div class="muted" style="font-size:13px;margin-top:-6px">Tu mejor ritmo sostenido para cada duración. Si la línea de los últimos ${PC.recent_days} días se acerca a la histórica, estás cerca de tu mejor forma en ese rango.</div>
      <div class="chart tall" id="pcChart"></div></div>` : ""}
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
  if (PC.all.length) paceCurveChart($("#pcChart"), PC);
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

function durLabel(sec) {
  return sec < 60 ? `${sec} s` : sec < 3600 ? `${sec / 60} min` : `${nf1.format(sec / 3600).replace(",0", "")} h`;
}
function paceCurveChart(el, PC) {
  const t = theme();
  const durs = PC.all.map((x) => x.duration);
  const byDur = (arr) => { const m = Object.fromEntries(arr.map((x) => [x.duration, x])); return durs.map((d) => m[d] || null); };
  const all = byDur(PC.all), year = byDur(PC.year), recent = byDur(PC.recent);
  const vals = PC.all.map((x) => x.pace).concat(PC.recent.map((x) => x.pace));
  return chart(el, {
    legend: { top: 0, textStyle: { color: t.text }, icon: "roundRect" }, grid: { top: 34 },
    xAxis: { type: "category", data: durs.map(durLabel), boundaryGap: false },
    yAxis: { type: "value", inverse: true, min: Math.floor(Math.min(...vals) / 15) * 15, max: Math.ceil(Math.max(...vals) / 15) * 15, axisLabel: { formatter: (v) => pace(v) } },
    tooltip: { formatter: (ps) => `${ps[0].axisValue}<br>` + ps.map((p) => {
      const src = [all, year, recent][p.seriesIndex][p.dataIndex];
      return `${p.marker}${p.seriesName}: <b>${pace(p.value)} /km</b>${src ? ` <span style="opacity:.7">· ${fdateShort(src.date)} ${src.date.slice(0, 4)}</span>` : ""}`;
    }).join("<br>") },
    series: [
      { name: "Histórico", type: "line", data: all.map((x) => x && x.pace), smooth: true, symbolSize: 6, lineStyle: { color: t.accent, width: 2.5 }, itemStyle: { color: t.accent }, areaStyle: { color: t.accent + "14" } },
      { name: String(new Date().getFullYear()), type: "line", data: year.map((x) => x && x.pace), smooth: true, symbolSize: 5, lineStyle: { color: t.blue, width: 1.8 }, itemStyle: { color: t.blue } },
      { name: `Últimos ${PC.recent_days} días`, type: "line", data: recent.map((x) => x && x.pace), smooth: true, symbolSize: 5, lineStyle: { color: t.good, width: 1.8, type: "dashed" }, itemStyle: { color: t.good } },
    ],
  });
}

// ================================================================ ESTADÍSTICAS
let statsGroup = "month";
let progMetric = "distance";
const PROG_UNITS = { distance: ["km", 1], time: ["h", 1], elev: ["m", 0] };
function doyLabel(doy) { const d = new Date(2025, 0, doy); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; }
function fmtMetric(v, metric) {
  if (v == null) return "–";
  return metric === "time" ? hours(v * 3600) : metric === "elev" ? `${nf0.format(v)} m` : `${nf1.format(v)} km`;
}
function progressionChart(el, P, infoEl, compact = false) {
  const t = theme();
  const thisYear = new Date().getFullYear();
  const palette = [t.faint, t.violet, t.blue, t.good, t.warn];
  const others = P.years.filter((y) => y.year !== thisYear);
  const days = Array.from({ length: 366 }, (_, i) => i + 1);
  if (infoEl) {
    const cur = P.same_date.find((x) => x.year === thisYear), prev = P.same_date.find((x) => x.year === thisYear - 1);
    const best = [...P.same_date].sort((a, b) => b.value - a.value)[0];
    infoEl.innerHTML = cur ? `A día de hoy: <b>${fmtMetric(cur.value, P.metric)}</b>${prev ? ` · ${cur.value >= prev.value ? "por delante" : "por detrás"} de ${thisYear - 1} en <b>${fmtMetric(Math.abs(cur.value - prev.value), P.metric)}</b>` : ""}${best && best.year !== thisYear ? ` · tu mejor año a estas alturas fue ${best.year} (${fmtMetric(best.value, P.metric)})` : ""}` : "";
  }
  return chart(el, {
    legend: compact ? undefined : { top: 0, textStyle: { color: t.text }, icon: "roundRect" },
    grid: { top: compact ? 8 : 34, left: 8, right: 14, bottom: 4, containLabel: true },
    xAxis: { type: "category", data: days, boundaryGap: false, axisLabel: { interval: (i) => [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334].includes(i), formatter: (v) => MONTHS[new Date(2025, 0, v).getMonth()] } },
    yAxis: { type: "value", axisLabel: { formatter: (v) => P.metric === "time" ? `${v} h` : nf0.format(v) } },
    tooltip: { formatter: (ps) => `${doyLabel(+ps[0].axisValue)}<br>` + ps.filter((p) => p.value != null).map((p) => `${p.marker}${p.seriesName}: <b>${fmtMetric(p.value, P.metric)}</b>`).join("<br>") },
    series: [
      ...others.map((y, i) => ({ name: String(y.year), type: "line", data: y.series, symbol: "none", lineStyle: { width: 1.4, color: palette[(others.length - 1 - i) % palette.length] }, itemStyle: { color: palette[(others.length - 1 - i) % palette.length] } })),
      ...P.years.filter((y) => y.year === thisYear).map((y) => ({ name: String(y.year), type: "line", data: y.series, symbol: "none", lineStyle: { width: 3, color: t.accent }, itemStyle: { color: t.accent }, areaStyle: { color: t.accent + "14" } })),
    ],
  });
}
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
      <div class="card wide" style="grid-column:1/-1"><h3>Progresión anual</h3>
        <div class="row" style="justify-content:space-between;margin-top:-4px"><div class="muted" style="font-size:13px" id="progInfo"></div>
          <div class="seg" id="progSeg">${[["distance", "Distancia"], ["time", "Tiempo"], ["elev", "Desnivel"]].map(([k, l]) => `<button data-m="${k}" class="${k === progMetric ? "on" : ""}">${l}</button>`).join("")}</div></div>
        <div class="chart xl" id="sProg"></div></div>
      <div class="card wide" style="grid-column:1/-1"><h3>Volumen y ritmo</h3><div class="chart xl" id="sVol"></div></div>
      <div class="card"><h3>¿Qué días corres?</h3><div class="chart" id="sWd" style="height:220px"></div></div>
      <div class="card"><h3>Distancias</h3><div class="chart" id="sHist" style="height:220px"></div></div>
    </div>
    <div class="section-title">Detalle por periodo</div>
    <div class="table-wrap"><table><thead><tr><th>Periodo</th><th>Carreras</th><th>Distancia</th><th>Tiempo</th><th>Ritmo</th><th>Desnivel</th><th>Más larga</th></tr></thead>
      <tbody>${[...S.periods].reverse().map((p) => `<tr><td>${label(p.period)}</td><td class="num">${p.n}</td><td class="num">${km(p.dist)} km</td><td class="num">${hours(p.secs)}</td><td class="num">${pace(p.pace)}</td><td class="num">${int(p.elev)} m</td><td class="num">${km(p.longest)} km</td></tr>`).join("")}</tbody></table></div>`;
  $$("#grp button").forEach((b) => (b.onclick = () => { statsGroup = b.dataset.g; rerender(); }));
  const drawProg = async () => {
    const P = await api(`/api/progression?metric=${progMetric}`);
    progressionChart($("#sProg"), P, $("#progInfo"));
  };
  $$("#progSeg button").forEach((b) => (b.onclick = () => {
    progMetric = b.dataset.m; $$("#progSeg button").forEach((x) => x.classList.toggle("on", x === b));
    const c = echarts.getInstanceByDom($("#sProg")); if (c) { charts = charts.filter((x) => x !== c); c.dispose(); }
    drawProg();
  }));
  drawProg();
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

// ================================================================ OBJETIVOS DE CARRERA
const RACE_DISTS = [[5000, "5 km"], [10000, "10 km"], [15000, "15 km"], [21097.5, "Media maratón"], [42195, "Maratón"]];
const PRIO = { A: "Objetivo principal: llegar en tu mejor forma", B: "Importante, con un afinamiento corto", C: "De preparación, sin bajar la carga" };
// TSB con signo y sin «-0»
function tsbFmt(v) { const n = Math.round(v); return n > 0 ? `+${n}` : String(n === 0 ? 0 : n); }
function raceDist(r) { return r.label || `${nf1.format(r.distance_m / 1000)} km`; }
function parseTime(str) {
  const parts = String(str || "").trim().split(":").map(Number);
  if (!parts.length || parts.some((x) => isNaN(x))) return null;
  return parts.reduce((acc, v) => acc * 60 + v, 0) || null;
}
const verdictTag = (v) => !v ? "" : v.label === "ambicioso" ? `<span class="tag warn">Ambicioso (${v.diff_pct}%)</span>`
  : v.label === "realista" ? `<span class="tag good">Realista</span>` : `<span class="tag blue">Conservador (+${v.diff_pct}%)</span>`;

route("objetivos", async (view) => {
  const L = await api("/api/races");
  const card = (r) => {
    const p = r.prediction || {};
    return `<a class="card" href="#/objetivo/${r.id}" style="display:block">
      <h3>${fdate(r.date)} <span class="tag ${r.priority === "A" ? "accent" : ""}">${r.priority}</span></h3>
      <div class="mid">${esc(r.name)}</div><div class="muted" style="font-size:13px">${raceDist(r)}${r.goal_time_s ? ` · objetivo ${dur(r.goal_time_s)} (${pace(r.goal_pace)} /km)` : ""}</div>
      ${r.days_left >= 0
        ? `<div class="row" style="justify-content:space-between;margin-top:10px"><span><span class="big num" style="font-size:30px">${r.days_left}</span> <span class="muted">días</span></span>
             <span style="text-align:right"><span class="muted" style="font-size:12px">Predicción hoy</span><br><b class="num">${p.estimate ? dur(p.estimate) : "–"}</b></span></div>`
        : r.result && r.result.time_s ? `<div class="row" style="justify-content:space-between;margin-top:10px"><span class="big num" style="font-size:30px">${dur(r.result.time_s)}</span>
             ${r.result.vs_goal_s != null ? `<span class="tag ${r.result.vs_goal_s <= 0 ? "good" : "warn"}">${r.result.vs_goal_s <= 0 ? "Objetivo cumplido" : "+" + dur(r.result.vs_goal_s) + " sobre el objetivo"}</span>` : ""}</div>`
        : `<div class="muted" style="margin-top:10px;font-size:13px">Sin resultado enlazado</div>`}
    </a>`;
  };
  view.innerHTML = `
    <div class="page-head"><div><h1>Objetivos</h1><div class="sub">Tus carreras objetivo: predicción, preparación y forma prevista para el día</div></div>
      <button class="btn primary" id="addRace">Añadir carrera</button></div>
    <div class="card" id="raceForm" hidden style="margin-bottom:16px">${raceFormHtml()}</div>
    ${L.upcoming.length ? `<div class="grid">${L.upcoming.map(card).join("")}</div>` : `<div class="card empty"><h2>Sin carreras a la vista</h2><p>Añade la próxima carrera que quieras preparar: verás la cuenta atrás, una predicción de tu tiempo según tu forma, cómo llegarás de fresco y qué te falta en la preparación.</p></div>`}
    ${L.past.length ? `<div class="section-title">Carreras pasadas</div><div class="grid">${L.past.map(card).join("")}</div>` : ""}`;
  $("#addRace").onclick = () => { const f = $("#raceForm"); f.hidden = !f.hidden; if (!f.hidden) $("#rfName").focus(); };
  setupRaceForm(null, (id) => { location.hash = `#/objetivo/${id}`; });
});

function raceFormHtml(r) {
  const preset = r ? RACE_DISTS.find(([d]) => Math.abs(d - r.distance_m) < 1) : RACE_DISTS[3];
  return `<h3>${r ? "Editar carrera" : "Nueva carrera"}</h3>
    <form id="rf" class="form-grid">
      <label class="field">Nombre<input type="text" id="rfName" required maxlength="80" placeholder="Maratón de Valencia" value="${esc(r ? r.name : "")}"></label>
      <label class="field">Fecha<input type="date" id="rfDate" required value="${esc(r ? r.date : "")}"></label>
      <label class="field">Distancia<select id="rfDist">${RACE_DISTS.map(([d, l]) => `<option value="${d}" ${preset && preset[0] === d ? "selected" : ""}>${l}</option>`).join("")}<option value="custom" ${r && !preset ? "selected" : ""}>Otra…</option></select></label>
      <label class="field" id="rfCustomWrap" ${r && !preset ? "" : "hidden"}>Km<input type="number" id="rfCustom" min="1" max="250" step="0.1" value="${r && !preset ? r.distance_m / 1000 : ""}"></label>
      <label class="field">Tiempo objetivo<input type="text" id="rfGoal" placeholder="h:mm:ss (opcional)" inputmode="numeric" value="${r && r.goal_time_s ? dur(r.goal_time_s) : ""}"></label>
      <label class="field">Prioridad<select id="rfPrio">${Object.entries(PRIO).map(([k, l]) => `<option value="${k}" ${(r ? r.priority : "A") === k ? "selected" : ""}>${k} · ${l}</option>`).join("")}</select></label>
      <label class="field" style="grid-column:1/-1">Notas<input type="text" id="rfNotes" maxlength="500" value="${esc(r && r.notes ? r.notes : "")}" placeholder="Circuito, desnivel, estrategia…"></label>
      <div class="row"><button class="btn primary">Guardar</button>${r ? `<button type="button" class="btn ghost" id="rfDelete" style="color:var(--bad)">Eliminar</button>` : ""}</div>
    </form><div id="rfMsg"></div>`;
}

function setupRaceForm(r, done) {
  $("#rfDist").onchange = (e) => { $("#rfCustomWrap").hidden = e.target.value !== "custom"; };
  $("#rf").onsubmit = async (e) => {
    e.preventDefault();
    const dv = $("#rfDist").value;
    const goalStr = $("#rfGoal").value.trim();
    const goal = goalStr ? parseTime(goalStr) : null;
    if (goalStr && !goal) { $("#rfMsg").innerHTML = `<p class="tag bad">Escribe el tiempo como h:mm:ss, por ejemplo 1:45:00</p>`; return; }
    const body = { name: $("#rfName").value, date: $("#rfDate").value, priority: $("#rfPrio").value, notes: $("#rfNotes").value,
      distance_m: dv === "custom" ? +$("#rfCustom").value * 1000 : +dv, goal_time_s: goal };
    try {
      if (r) { await api(`/api/races/${r.id}`, { method: "PUT", body }); done(r.id); }
      else { const res = await api("/api/races", { method: "POST", body }); done(res.id); }
      toast("Carrera guardada");
    } catch (err) { $("#rfMsg").innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`; }
  };
  const del = $("#rfDelete");
  if (del) del.onclick = async () => {
    if (!confirm(`¿Eliminar «${r.name}»?`)) return;
    await api(`/api/races/${r.id}`, { method: "DELETE" }); location.hash = "#/objetivos";
  };
}

route("objetivo", async (view, id) => {
  const r = await api(`/api/races/${id}`);
  const p = r.prediction || {};
  const upcoming = r.days_left >= 0;
  const predRow = (label, t, extra = "") => `<div class="rec-row"><span>${label}${extra}</span><span class="faint num" style="font-size:12px">${t ? pace(t / (r.distance_m / 1000)) + " /km" : ""}</span><span class="t num">${t ? dur(t) : "–"}</span></div>`;
  const ck = r.checklist;
  view.innerHTML = `
    <div class="page-head"><div><a class="muted" href="#/objetivos">← Objetivos</a><h1>${esc(r.name)}</h1>
      <div class="sub">${fdate(r.date)} · ${raceDist(r)} · <span class="tag ${r.priority === "A" ? "accent" : ""}">Prioridad ${r.priority}</span>${r.notes ? ` · ${esc(r.notes)}` : ""}</div></div>
      <button class="btn" id="editRace">Editar</button></div>
    <div class="card" id="raceForm" hidden style="margin-bottom:16px">${raceFormHtml(r)}</div>
    <div class="grid">
      ${upcoming ? `<div class="card"><h3>Cuenta atrás</h3><div class="big num">${r.days_left}<small>${r.days_left === 1 ? "día" : "días"}</small></div>
        <div class="muted">${r.goal_time_s ? `Objetivo <b>${dur(r.goal_time_s)}</b> · ${pace(r.goal_pace)} /km` : "Sin tiempo objetivo"}</div>
        ${ck && ck.verdict ? `<div style="margin-top:10px">${verdictTag(ck.verdict)}</div><div class="faint" style="font-size:12px;margin-top:6px">Comparado con tu predicción actual (${dur(p.estimate)}).</div>` : ""}</div>`
      : `<div class="card"><h3>Resultado</h3>${r.result && r.result.time_s ? `<a href="#/carrera/${r.result.activity.id}"><div class="big num">${dur(r.result.time_s)}</div></a>
          <div class="muted">${pace(r.result.time_s / (r.distance_m / 1000))} /km${r.goal_time_s ? ` · objetivo ${dur(r.goal_time_s)}` : ""}</div>
          ${r.result.vs_goal_s != null ? `<div style="margin-top:10px"><span class="tag ${r.result.vs_goal_s <= 0 ? "good" : "warn"}">${r.result.vs_goal_s <= 0 ? "Objetivo cumplido por " + dur(-r.result.vs_goal_s) : dur(r.result.vs_goal_s) + " sobre el objetivo"}</span></div>` : ""}`
        : `<div class="muted">No se ha encontrado la actividad de la carrera.</div>`}
        ${r.candidates.length ? `<label class="field" style="margin-top:12px">Actividad de la carrera<select id="resSel"><option value="">Ninguna</option>${r.candidates.map((c) => `<option value="${c.id}" ${r.result && r.result.activity.id === c.id ? "selected" : ""}>${esc(c.name)} · ${km(c.distance_m)} km</option>`).join("")}</select></label>` : ""}</div>`}
      <div class="card"><h3>${upcoming ? "Predicción con tu forma actual" : "Predicción que tenías antes de la carrera"}</h3>
        <div class="rec-list">
          ${predRow("VDOT (Daniels)", p.vdot, p.vdot_value ? ` <span class="faint" style="font-size:12px">· VDOT ${nf1.format(p.vdot_value)}</span>` : "")}
          ${predRow("Riegel", p.riegel, p.riegel_from ? ` <span class="faint" style="font-size:12px">· desde ${labelFor(p.riegel_from.distance_m)}</span>` : "")}
          ${upcoming ? predRow("Garmin", p.garmin) : ""}
          <div class="rec-row" style="border-top:1px solid var(--line)"><b>Estimación</b><span class="faint num" style="font-size:12px">${p.estimate ? pace(p.estimate / (r.distance_m / 1000)) + " /km" : ""}</span><span class="t num" style="color:var(--accent)">${p.estimate ? dur(p.estimate) : "–"}</span></div>
        </div>
        <p class="faint" style="font-size:12px;margin:8px 0 0">${p.based_on ? `Basada en tus mejores tramos de los últimos 90 días (el de más valor: ${labelFor(p.based_on.distance_m)} en ${dur(p.based_on.time_s)}). Si en entrenamiento no has ido a tope, la predicción es conservadora.` : "Aún no hay tramos recientes suficientes para predecir."}</p></div>
      ${ck ? `<div class="card"><h3>Preparación</h3><div class="rec-list">${ck.items.map((i) => `<div class="rec-row" style="grid-template-columns:auto 1fr auto">
          <span style="font-size:18px">${i.ok ? "✅" : "⚠️"}</span><span>${i.label}<br><span class="faint" style="font-size:12px">recomendado ${typeof i.target === "number" ? (i.id === "freq" ? "≥ " : "≥ ") + i.target + (i.unit ? " " + i.unit : "") : i.target}</span></span>
          <span class="t num">${i.id === "tsb" && i.value > 0 ? "+" : ""}${typeof i.value === "number" ? nf1.format(i.value).replace(",0", "") : i.value}${i.unit ? " " + i.unit : ""}</span></div>`).join("")}</div>
        <p class="faint" style="font-size:12px;margin:8px 0 0">Orientaciones generales para un corredor popular; adáptalas a tu plan y a tu experiencia.</p></div>` : ""}
      ${upcoming || r.has_plan ? `<div class="card" id="planCard"><h3>Plan de entrenamiento</h3><div class="muted">Cargando…</div></div>` : ""}
      ${upcoming && r.projection ? `<div class="card wide" style="grid-column:1/-1"><h3>Forma prevista hasta el día de la carrera</h3>
        <div class="muted" style="font-size:13px;margin-top:-6px">Suponiendo que mantienes tu carga media de las últimas 4 semanas${r.priority !== "C" ? ` y la reduces al 60 % los últimos ${r.projection.taper_days} días (afinamiento)` : ""}.
          Forma (TSB) el día de la carrera: <b>${tsbFmt(r.projection.race_tsb)}</b>${r.projection_no_taper ? ` · sin afinamiento: ${tsbFmt(r.projection_no_taper.race_tsb)}` : ""}.
          Rango ideal para prioridad ${r.priority}: ${ck.tsb_window[0] > 0 ? "+" : ""}${ck.tsb_window[0]} a +${ck.tsb_window[1]}.</div>
        <div class="chart xl" id="projChart"></div></div>` : ""}
    </div>`;
  $("#editRace").onclick = () => { const f = $("#raceForm"); f.hidden = !f.hidden; };
  setupRaceForm(r, () => rerender());
  const rs = $("#resSel");
  if (rs) rs.onchange = async (e) => { await api(`/api/races/${r.id}/result`, { method: "PUT", body: { activity_id: e.target.value || null } }); rerender(); };
  if (upcoming && r.projection) projectionChart($("#projChart"), r);
  if ($("#planCard")) renderPlanCard($("#planCard"), r);
});

// ================================================================ PLAN DE ENTRENAMIENTO
const SESSION_TYPES = {
  easy: { label: "Suave", cls: "" }, long: { label: "Tirada larga", cls: "blue" }, intervals: { label: "Series", cls: "bad" },
  tempo: { label: "Umbral", cls: "warn" }, specific: { label: "Ritmo carrera", cls: "accent" }, fartlek: { label: "Fartlek", cls: "warn" },
  strides: { label: "Suave + rectas", cls: "" }, shakeout: { label: "Activación", cls: "" }, race: { label: "Carrera", cls: "accent" },
};
const PHASES = { base: "Base", build: "Construcción", peak: "Pico", taper: "Afinamiento" };
const WEEK_ORDER = [1, 2, 3, 4, 5, 6, 0];
const PLAN_OPEN = {}; // semanas desplegadas por plan, para no plegarlas al actualizar
const PSTATUS = { planned: "Pendiente", done: "Hecha", skipped: "Saltada", missed: "No hecha" };
const typeTag = (t) => `<span class="tag ${(SESSION_TYPES[t] || {}).cls || ""}">${(SESSION_TYPES[t] || { label: t }).label}</span>`;
function isoToday() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }

function planFormHtml(params, dflt) {
  const v = params || dflt || {};
  return `<form id="planForm" class="form-grid" style="margin-top:8px">
      <label class="field">Días por semana<select id="pfDays">${[3, 4, 5, 6].map((n) => `<option value="${n}" ${(v.days_per_week || 4) === n ? "selected" : ""}>${n} días</option>`).join("")}</select></label>
      <label class="field">Tirada larga<select id="pfLong"><option value="6" ${(v.long_day ?? 6) === 6 ? "selected" : ""}>Domingo</option><option value="5" ${v.long_day === 5 ? "selected" : ""}>Sábado</option></select></label>
      <label class="field">Km semanales de partida<input type="number" id="pfKm" min="5" max="250" step="1" value="${Math.round(v.start_km || 20)}"></label>
      <div class="row" style="align-self:end"><button class="btn primary">${params ? "Rehacer plan" : "Crear plan"}</button></div>
    </form><div id="pfMsg"></div>`;
}
function setupPlanForm(raceId, done) {
  $("#planForm").onsubmit = async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button"); btn.disabled = true;
    try {
      await api(`/api/races/${raceId}/plan`, { method: "POST", body: { days_per_week: +$("#pfDays").value, long_day: +$("#pfLong").value, start_km: +$("#pfKm").value } });
      toast("Plan listo"); done();
    } catch (err) { $("#pfMsg").innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`; btn.disabled = false; }
  };
}

async function renderPlanCard(card, r) {
  const P = await api(`/api/races/${r.id}/plan`);
  if (!P.plan) {
    if (!P.defaults) { card.remove(); return; }
    const D = P.defaults;
    card.innerHTML = `<h3>Plan de entrenamiento</h3>
      <div class="muted" style="font-size:14px">Semanas hasta la carrera con sus sesiones y ritmos, ajustadas a tu forma. Las sesiones se marcan solas al sincronizar tus carreras.</div>
      <div class="faint" style="font-size:12px;margin-top:6px">Ahora corres ${nf1.format(D.current_weekly_km)} km por semana (media de 4 semanas) y tu carrera más larga reciente es de ${nf1.format(D.current_long_km)} km.</div>
      ${planFormHtml(null, D)}`;
    setupPlanForm(r.id, () => { location.hash = `#/plan/${r.id}`; });
    return;
  }
  const S = P.summary, cur = P.weeks.find((w) => w.current) || P.weeks.find((w) => !w.past);
  card.innerHTML = `<h3>Plan de entrenamiento ${cur ? `<span class="tag">${PHASES[cur.phase]}</span>` : ""}</h3>
    <div class="kpis" style="margin-top:4px">
      <div class="kpi"><div class="v num">${cur ? cur.index : P.weeks.length}/${P.weeks.length}</div><div class="l">Semana</div></div>
      <div class="kpi"><div class="v num">${S.sessions_done}/${S.sessions_due}</div><div class="l">Sesiones hechas</div></div>
      <div class="kpi"><div class="v num">${S.km_planned ? Math.round((100 * S.km_done) / S.km_planned) + "%" : "–"}</div><div class="l">Km cumplidos</div></div>
    </div>
    <a class="more" href="#/plan/${r.id}">Ver plan →</a>`;
}

route("plan", async (view, id) => {
  const [r, P] = await Promise.all([api(`/api/races/${id}`), api(`/api/races/${id}/plan`)]);
  if (!P.plan) { location.hash = `#/objetivo/${id}`; return; }
  const pa = P.plan.paces, S = P.summary, todayIso = isoToday();
  const paceRow = (l, v, note) => `<div class="rec-row"><span>${l}<br><span class="faint" style="font-size:12px">${note}</span></span><span></span><span class="t num">${v}</span></div>`;
  const sessionRow = (s) => {
    const done = s.status === "done", act = s.activity_id && s.act_distance;
    return `<div class="psess ${s.status} ${s.date === todayIso ? "today" : ""}" data-id="${s.id}">
      <div class="pday"><b>${WEEKDAYS[new Date(s.date + "T12:00:00").getDay()]}</b><span class="faint">${fdateShort(s.date)}</span></div>
      <div class="pbody">
        <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">${typeTag(s.type)}<b class="num">${s.type === "race" ? raceDist(r) : nf1.format(s.distance_km).replace(",0", "") + " km"}</b>
          ${act ? `<a class="faint" style="font-size:12px" href="#/carrera/${s.activity_id}">✓ ${km(s.act_distance)} km a ${pace(s.act_time / (s.act_distance / 1000))} /km</a>` : ""}</div>
        <div class="pdesc">${esc(s.description)}</div>
        <div class="pmove" hidden><input type="date" value="${s.date}"> <button class="btn small" data-act="move">Mover</button></div>
      </div>
      ${s.type === "race" ? `<span class="tag ${done ? "good" : ""}">${done ? "Hecha" : "🏁"}</span>` : `<div class="pact">
        <select data-act="status" title="Estado">${["planned", "done", "skipped"].map((k) => `<option value="${k}" ${s.status === k ? "selected" : ""}>${PSTATUS[k]}</option>`).join("")}${s.status === "missed" ? `<option value="missed" selected disabled>${PSTATUS.missed}</option>` : ""}</select>
        ${s.status !== "done" ? `<button class="btn small ghost" data-act="showmove" title="Cambiar de día">Mover</button>` : ""}</div>`}
    </div>`;
  };
  const weekHtml = (w) => {
    const compl = w.compliance;
    const cls = compl == null ? "" : compl >= 90 ? "good" : compl >= 70 ? "warn" : "bad";
    const open = PLAN_OPEN[id] ? PLAN_OPEN[id].has(w.index) : w.current || (!P.weeks.some((x) => x.current) && w === P.weeks.find((x) => !x.past));
    return `<details class="card pweek ${w.current ? "current" : ""}" data-week="${w.index}" ${open ? "open" : ""}>
      <summary><span><b>Semana ${w.index}</b> · ${PHASES[w.phase]}${w.recovery ? ` <span class="tag">Descarga</span>` : ""}${w.current ? ` <span class="tag accent">Esta semana</span>` : ""}
        <span class="faint" style="font-size:12px"> · ${fdateShort(w.monday)}</span></span>
        <span class="num" style="font-size:13px">${w.past || w.current ? `${nf1.format(w.done_km)} / ` : ""}${nf1.format(w.planned_km)} km ${compl != null ? `<span class="tag ${cls}">${compl}%</span>` : ""}</span></summary>
      <div class="psessions">${w.sessions.map(sessionRow).join("") || `<div class="muted">Sin sesiones.</div>`}</div>
    </details>`;
  };
  view.innerHTML = `
    <div class="page-head"><div><a class="muted" href="#/objetivo/${r.id}">← ${esc(r.name)}</a><h1>Plan de entrenamiento</h1>
      <div class="sub">${P.weeks.length} semanas hasta el ${fdate(r.date)} · ${raceDist(r)} · ${P.plan.params.days_per_week} días por semana</div></div>
      <button class="btn" id="redoPlan">Ajustar plan</button></div>
    <div class="card" id="redoCard" hidden style="margin-bottom:16px"><h3>Rehacer el plan</h3>
      <div class="muted" style="font-size:13px">Se rehacen las sesiones pendientes desde hoy con tu forma y ritmos actuales. Lo ya hecho y lo que hayas marcado a mano se conserva.</div>
      ${planFormHtml(P.plan.params)}
      <div class="row" style="margin-top:10px"><button class="btn ghost small" id="delPlan" style="color:var(--bad)">Eliminar plan</button></div></div>
    <div class="grid">
      <div class="card" style="align-self:start"><h3>Cumplimiento</h3>
        <div class="kpis" style="margin-top:4px">
          <div class="kpi"><div class="v num">${S.sessions_done}/${S.sessions_due}</div><div class="l">Sesiones hechas</div></div>
          <div class="kpi"><div class="v num">${nf0.format(S.km_done)}<small style="font-size:12px"> / ${nf0.format(S.km_planned)}</small></div><div class="l">Km hasta hoy</div></div>
          <div class="kpi"><div class="v num">${S.km_planned ? Math.round((100 * S.km_done) / S.km_planned) + "%" : "–"}</div><div class="l">Del volumen previsto</div></div>
        </div>
        <p class="faint" style="font-size:12px;margin:10px 0 0">Una sesión se da por hecha si ese día hay una carrera tuya. Puedes cambiar el estado o moverla de día.</p></div>
      <div class="card" style="align-self:start"><h3>Tus ritmos <span class="tag">VDOT ${nf1.format(pa.vdot)}</span></h3>
        ${pa.race_from_goal && r.checklist && r.checklist.verdict && r.checklist.verdict.label === "ambicioso" ? `<p class="tag warn" style="white-space:normal;margin:0 0 6px">Tu ritmo objetivo es más rápido que lo que predice tu forma actual (${pace(r.prediction.estimate / (r.distance_m / 1000))} /km). Las sesiones a ritmo de carrera te dirán si es alcanzable.</p>` : ""}
        <div class="rec-list">
        ${paceRow("Suave y tirada larga", `${pace(pa.easy_fast)}–${pace(pa.easy_slow)}`, "Conversacional, la mayor parte del volumen")}
        ${paceRow("Ritmo de carrera", pace(pa.race), pa.race_from_goal ? "Según tu tiempo objetivo" : "Según tu predicción")}
        ${paceRow("Maratón", pace(pa.marathon), "Tiradas con tramos a ritmo")}
        ${paceRow("Umbral", pace(pa.threshold), "«Cómodamente duro», 20–30 min")}
        ${paceRow("Series", pace(pa.interval), "Tramos de 3–5 min")}
        ${paceRow("Repeticiones", pace(pa.repetition), "Rectas y tramos cortos")}
      </div><p class="faint" style="font-size:12px;margin:8px 0 0">Ritmos de Jack Daniels para tu VDOT, en min/km. Se recalculan al ajustar el plan.</p></div>
      <div class="card wide" style="grid-column:1/-1"><h3>Kilómetros previstos y hechos por semana</h3><div class="chart" id="planChart" style="height:260px"></div></div>
    </div>
    <div class="section-title">Semanas</div>
    ${P.weeks.map(weekHtml).join("")}`;
  $("#redoPlan").onclick = () => { const c = $("#redoCard"); c.hidden = !c.hidden; };
  $$(".pweek").forEach((d) => d.addEventListener("toggle", () => {
    PLAN_OPEN[id] = new Set($$(".pweek[open]").map((x) => +x.dataset.week));
  }));
  setupPlanForm(r.id, () => rerender());
  $("#delPlan").onclick = async () => {
    if (!confirm("¿Eliminar el plan? Se perderá el seguimiento de las sesiones.")) return;
    await api(`/api/races/${r.id}/plan`, { method: "DELETE" }); location.hash = `#/objetivo/${r.id}`;
  };
  $$(".psess").forEach((row) => {
    const sid = row.dataset.id;
    const sel = row.querySelector('[data-act="status"]');
    if (sel) sel.onchange = async () => { try { await api(`/api/plan-sessions/${sid}`, { method: "PUT", body: { status: sel.value } }); rerender(); } catch (e) { toast(e.message, true); } };
    const sm = row.querySelector('[data-act="showmove"]');
    if (sm) sm.onclick = () => { const m = row.querySelector(".pmove"); m.hidden = !m.hidden; };
    const mv = row.querySelector('[data-act="move"]');
    if (mv) mv.onclick = async () => {
      try { await api(`/api/plan-sessions/${sid}`, { method: "PUT", body: { date: row.querySelector(".pmove input").value } }); toast("Sesión movida"); rerender(); }
      catch (e) { toast(e.message, true); }
    };
  });
  const t = theme();
  const phaseColor = { base: t.blue, build: t.accent, peak: t.violet, taper: t.good };
  chart($("#planChart"), {
    legend: { top: 0, textStyle: { color: t.text } }, grid: { top: 34, bottom: 30 },
    xAxis: { type: "category", data: P.weeks.map((w) => `S${w.index}`) }, yAxis: { type: "value" },
    tooltip: { formatter: (ps) => { const w = P.weeks[ps[0].dataIndex]; return `Semana ${w.index} · ${PHASES[w.phase]}<br>${fdateShort(w.monday)}<br>` + ps.filter((p) => p.value != null).map((p) => `${p.marker}${p.seriesName}: <b>${nf1.format(p.value)} km</b>`).join("<br>"); } },
    series: [
      { name: "Previsto", type: "bar", barGap: "-100%", itemStyle: { color: t.faint + "80" }, data: P.weeks.map((w) => ({ value: w.planned_km, itemStyle: { color: phaseColor[w.phase] + "40", borderRadius: [4, 4, 0, 0] } })) },
      { name: "Hecho", type: "bar", data: P.weeks.map((w) => (w.past || w.current ? w.done_km : null)), barWidth: "45%", itemStyle: { color: t.accent, borderRadius: [4, 4, 0, 0] } },
    ],
  });
});

function projectionChart(el, r) {
  const t = theme();
  const hist = r.history || [], proj = r.projection.series, noTaper = r.projection_no_taper ? r.projection_no_taper.series : null;
  const dates = hist.map((x) => x.date).concat(proj.map((x) => x.date));
  const pad = (arr, before) => Array(before).fill(null).concat(arr);
  const [lo, hi] = r.checklist.tsb_window;
  const taperStart = proj.length - r.projection.taper_days - 1;
  return chart(el, {
    legend: { top: 0, textStyle: { color: t.text }, icon: "roundRect" }, grid: { top: 34, bottom: 30 },
    xAxis: { type: "category", data: dates, boundaryGap: false, axisLabel: { formatter: (v) => fdateShort(v) } },
    yAxis: { type: "value" },
    tooltip: { formatter: (ps) => `${fdate(ps[0].axisValue)}<br>` + ps.filter((p) => p.value != null).map((p) => `${p.marker}${p.seriesName}: <b>${nf0.format(p.value)}</b>`).join("<br>") },
    series: [
      { name: "Fitness (CTL)", type: "line", data: hist.map((x) => x.ctl).concat(Array(proj.length).fill(null)), symbol: "none", lineStyle: { color: t.blue, width: 2.5 }, itemStyle: { color: t.blue } },
      { name: "Fitness previsto", type: "line", data: pad(proj.map((x) => x.ctl), hist.length), symbol: "none", lineStyle: { color: t.blue, width: 2, type: "dashed" }, itemStyle: { color: t.blue } },
      { name: "Forma (TSB)", type: "line", data: hist.map((x) => x.tsb).concat(Array(proj.length).fill(null)), symbol: "none", lineStyle: { color: t.good, width: 2.5 }, itemStyle: { color: t.good } },
      { name: "Forma prevista", type: "line", data: pad(proj.map((x) => x.tsb), hist.length), symbol: "none", lineStyle: { color: t.good, width: 2, type: "dashed" }, itemStyle: { color: t.good },
        markArea: { silent: true, itemStyle: { color: t.good + "18" }, data: [[{ yAxis: lo }, { yAxis: hi }]] },
        markLine: { symbol: "none", silent: true, lineStyle: { color: t.accent }, label: { color: t.text, formatter: "carrera", position: "insideEndTop" }, data: [{ xAxis: dates.length - 1 }] } },
      ...(noTaper ? [{ name: "Forma sin afinar", type: "line", data: pad(noTaper.map((x) => x.tsb), hist.length), symbol: "none", lineStyle: { color: t.faint, width: 1.4, type: "dotted" }, itemStyle: { color: t.faint } }] : []),
      ...(r.priority !== "C" && taperStart > 0 ? [{ name: "Afinamiento", type: "line", data: [], markArea: { silent: true, itemStyle: { color: t.accent + "12" }, label: { color: t.text, formatter: "afinamiento", position: "insideTop" },
        data: [[{ xAxis: hist.length + taperStart }, { xAxis: dates.length - 1 }]] } }] : []),
    ],
  });
}

// ================================================================ ZAPATILLAS
route("zapatillas", async (view) => {
  const S = await api("/api/shoes");
  const active = S.filter((x) => !x.retired), retired = S.filter((x) => x.retired);
  const colors = { ok: "var(--accent)", soon: "var(--warn)", replace: "var(--bad)", retired: "var(--faint)" };
  const label = { ok: "", soon: `<span class="tag warn">Cerca del límite</span>`, replace: `<span class="tag bad">Toca cambiarlas</span>`, retired: `<span class="tag">Retiradas</span>` };
  const shoeCard = (x) => `
    <div class="card">
      <h3>${esc(x.brand || "Zapatilla")} ${x.is_default ? `<span class="tag accent">Por defecto</span>` : ""} ${label[x.status]}</h3>
      <div class="mid">${esc(x.name)}</div>
      <div class="row" style="justify-content:space-between;margin-top:8px"><span class="big num" style="font-size:30px">${nf0.format(x.km)}<small>km</small></span><span class="muted num">de ${nf0.format(x.limit_km)} km</span></div>
      <div class="progress"><div style="width:${Math.min(100, x.pct || 0)}%;background:${colors[x.status]}"></div></div>
      <div class="muted" style="font-size:12px">${x.runs} carreras${x.initial_km ? ` · ${nf0.format(x.initial_km)} km previos` : ""}${x.first_used ? ` · desde ${fdateShort(x.first_used)} ${x.first_used.slice(0, 4)}` : ""}${x.last_used ? ` · última ${fdateShort(x.last_used)}` : ""}</div>
      ${x.notes ? `<div class="faint" style="font-size:12px;margin-top:6px">${esc(x.notes)}</div>` : ""}
      <div class="row" style="margin-top:12px">
        ${x.retired ? `<button class="btn small" data-unretire="${x.id}">Volver a usar</button>`
          : `${x.is_default ? "" : `<button class="btn small" data-default="${x.id}">Por defecto</button>`}<button class="btn small ghost" data-retire="${x.id}">Retirar</button>`}
        <button class="btn small ghost" data-edit="${x.id}">Editar</button>
        <button class="btn small ghost" data-delshoe="${x.id}" style="color:var(--bad)">Eliminar</button>
      </div>
    </div>`;
  view.innerHTML = `
    <div class="page-head"><div><h1>Zapatillas</h1><div class="sub">Kilómetros de cada par y aviso cuando se acercan al límite</div></div>
      <button class="btn primary" id="addShoe">Añadir zapatillas</button></div>
    <div class="card" id="shoeFormCard" hidden style="margin-bottom:16px"><h3 id="shoeFormTitle">Nuevas zapatillas</h3>
      <form id="shoeForm" class="form-grid">
        <label class="field">Modelo<input type="text" id="sfName" required maxlength="60" placeholder="Pegasus 41"></label>
        <label class="field">Marca<input type="text" id="sfBrand" maxlength="60" placeholder="Nike"></label>
        <label class="field">En uso desde<input type="date" id="sfStart"></label>
        <label class="field">Km previos<input type="number" id="sfInit" min="0" step="1" value="0"></label>
        <label class="field">Límite (km)<input type="number" id="sfLimit" min="50" max="5000" step="10" value="700"></label>
        <label class="field" style="grid-column:1/-1">Notas<input type="text" id="sfNotes" maxlength="300" placeholder="Talla, para qué las usas…"></label>
        <label class="check"><input type="checkbox" id="sfDefault" checked> Usar por defecto en las carreras nuevas</label>
        <label class="check" id="sfAssignWrap"><input type="checkbox" id="sfAssign" checked> Asignarlas a las carreras sin zapatilla desde esa fecha</label>
        <div class="row"><button class="btn primary">Guardar</button><button type="button" class="btn ghost" id="sfCancel">Cancelar</button></div>
      </form><div id="sfMsg"></div>
      <div class="faint" style="font-size:12px;margin-top:8px">Como referencia, unas zapatillas de entrenamiento suelen durar entre 600 y 900 km; las de competición, bastante menos.</div></div>
    ${S.length ? `<div class="grid">${active.map(shoeCard).join("")}</div>
      ${retired.length ? `<div class="section-title">Retiradas</div><div class="grid">${retired.map(shoeCard).join("")}</div>` : ""}`
    : `<div class="card empty"><h2>Aún no has añadido zapatillas</h2><p>Añade las que usas, márcalas por defecto y cada carrera nueva sumará sus kilómetros automáticamente. Puedes cambiar la zapatilla de cualquier carrera desde su detalle.</p></div>`}`;
  let editing = null;
  const form = $("#shoeFormCard");
  const open = (x) => {
    editing = x || null;
    form.hidden = false;
    $("#shoeFormTitle").textContent = x ? "Editar zapatillas" : "Nuevas zapatillas";
    $("#sfName").value = x ? x.name : ""; $("#sfBrand").value = x ? x.brand || "" : "";
    $("#sfStart").value = x ? x.start_date || "" : new Date().toISOString().slice(0, 10);
    $("#sfInit").value = x ? x.initial_km : 0; $("#sfLimit").value = x ? x.limit_km : 700; $("#sfNotes").value = x ? x.notes || "" : "";
    $("#sfDefault").checked = x ? !!x.is_default : true;
    $("#sfAssignWrap").hidden = !!x;
    $("#sfName").focus();
  };
  $("#addShoe").onclick = () => open(null);
  $("#sfCancel").onclick = () => { form.hidden = true; };
  $("#shoeForm").onsubmit = async (e) => {
    e.preventDefault();
    const body = { name: $("#sfName").value, brand: $("#sfBrand").value, start_date: $("#sfStart").value || null,
      initial_km: +$("#sfInit").value || 0, limit_km: +$("#sfLimit").value || 700, notes: $("#sfNotes").value, is_default: $("#sfDefault").checked };
    try {
      if (editing) await api(`/api/shoes/${editing.id}`, { method: "PUT", body });
      else await api("/api/shoes", { method: "POST", body: { ...body, assign_existing: $("#sfAssign").checked } });
      toast("Guardado"); rerender();
    } catch (err) { $("#sfMsg").innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`; }
  };
  const byId = Object.fromEntries(S.map((x) => [x.id, x]));
  const put = async (x, extra) => { await api(`/api/shoes/${x.id}`, { method: "PUT", body: { ...x, ...extra } }); rerender(); };
  $$("[data-edit]").forEach((b) => (b.onclick = () => open(byId[b.dataset.edit])));
  $$("[data-default]").forEach((b) => (b.onclick = () => put(byId[b.dataset.default], { is_default: true })));
  $$("[data-retire]").forEach((b) => (b.onclick = () => put(byId[b.dataset.retire], { retired: true })));
  $$("[data-unretire]").forEach((b) => (b.onclick = () => put(byId[b.dataset.unretire], { retired: false })));
  $$("[data-delshoe]").forEach((b) => (b.onclick = async () => {
    if (!confirm(`¿Eliminar «${byId[b.dataset.delshoe].name}»? Las carreras se conservan, sólo dejan de estar asignadas. Si ya no las usas, mejor «Retirar».`)) return;
    await api(`/api/shoes/${b.dataset.delshoe}`, { method: "DELETE" }); rerender();
  }));
});

// ================================================================ AJUSTES
route("ajustes", async (view) => {
  const [st, set, log, sessions, users] = await Promise.all([api("/api/status"), api("/api/settings"), api("/api/sync/log"),
    api("/api/account/sessions"), ME && ME.is_admin ? api("/api/admin/users") : Promise.resolve(null)]);
  const bk = ME && ME.is_admin ? await api("/api/admin/backups") : null;
  view.innerHTML = `
    <div class="page-head"><div><h1>Ajustes</h1><div class="sub">Modo Guerrero v${esc(st.version)}</div></div></div>
    <div class="grid">
      <div class="card"><h3>Cuenta de Garmin ${st.connected ? `<span class="tag good">Conectada</span>` : `<span class="tag bad">Sin conectar</span>`}</h3>
        <div id="garminBox"></div>
      </div>
      <div class="card"><h3>App en el móvil ${IS_STANDALONE ? `<span class="tag good">Instalada</span>` : ""}</h3>
        ${IS_STANDALONE ? `<p class="muted" style="font-size:14px;margin-top:0">Estás usando Modo Guerrero como app. Al volver a ella tras un rato, los datos se actualizan solos.</p>`
        : IS_IOS ? `<ol class="muted" style="font-size:14px;margin:0;padding-left:20px;line-height:1.7">
            <li>Abre esta página en <b>Safari</b>.</li>
            <li>Pulsa <b>Compartir</b> (el cuadrado con la flecha hacia arriba).</li>
            <li>Elige <b>Añadir a pantalla de inicio</b> y pulsa <b>Añadir</b>.</li>
            <li>Ábrela desde el icono e inicia sesión marcando «Recordar este dispositivo».</li></ol>`
        : `<p class="muted" style="font-size:14px;margin-top:0">En el móvil, abre esta página y usa <b>Añadir a pantalla de inicio</b> (en Safari, desde Compartir; en Chrome, desde el menú ⋮). Tendrás un icono propio y se abrirá a pantalla completa.</p>`}
        <p class="faint" style="font-size:12px;margin-bottom:0">Consejo: añádela usando la dirección de Tailscale de tu servidor (no <code>umbrel.local</code>), así funcionará también fuera de casa con Tailscale activo en el móvil.
          Dirección actual: <code>${esc(location.origin)}</code></p>
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
      ${users ? `<div class="card wide" style="grid-column:1/-1"><h3>Usuarios <span class="tag">${users.length}</span></h3>
        <p class="muted" style="font-size:13px;margin-top:0">Cada usuario tiene sus propios datos, su cuenta de Garmin y sus ajustes; nadie ve los datos de otro, tampoco el administrador.</p>
        <div class="table-wrap" style="border:0"><table>
          <thead><tr><th class="l">Usuario</th><th class="l">Garmin</th><th>Carreras</th><th class="l">Último acceso</th><th></th></tr></thead>
          <tbody>${users.map((u) => `<tr>
            <td class="l"><b>${esc(u.username)}</b> ${u.is_admin ? `<span class="tag accent">Admin</span>` : ""} ${u.must_change ? `<span class="tag warn">Contraseña temporal</span>` : ""}</td>
            <td class="l">${u.garmin ? `<span class="tag good">Conectado</span>` : `<span class="tag">No</span>`}</td>
            <td class="num">${int(u.runs)}</td>
            <td class="l faint">${u.last_seen ? esc(timeAgo(u.last_seen)) : "nunca"}</td>
            <td>${u.username.toLowerCase() === (ME.username || "").toLowerCase() ? `<span class="faint">Tú</span>` : `
              <button class="btn small ghost" data-reset="${u.id}" data-name="${esc(u.username)}">Restablecer contraseña</button>
              <button class="btn small ghost" data-mkadmin="${u.id}" data-val="${u.is_admin ? 0 : 1}">${u.is_admin ? "Quitar admin" : "Hacer admin"}</button>
              <button class="btn small ghost" data-del="${u.id}" data-name="${esc(u.username)}" style="color:var(--bad)">Eliminar</button>`}</td>
          </tr>`).join("")}</tbody></table></div>
        <h3 style="margin-top:20px">Crear usuario</h3>
        <form id="nu" class="form-grid">
          <label class="field">Usuario<input type="text" id="nuName" required minlength="3" maxlength="40" autocapitalize="none" autocorrect="off" spellcheck="false" autocomplete="off"></label>
          <label class="field">Contraseña temporal<input type="text" id="nuPass" required minlength="10" autocomplete="off" spellcheck="false"></label>
          <label class="check" style="align-self:end;padding-bottom:10px"><input type="checkbox" id="nuAdmin"> Administrador</label>
          <div class="row" style="align-self:end"><button type="button" class="btn" id="nuGen">Generar contraseña</button><button class="btn primary">Crear</button></div>
        </form>
        <div class="faint" style="font-size:12px;margin-top:6px">Pásale el usuario y la contraseña temporal. Al entrar por primera vez tendrá que elegir la suya y conectar su propia cuenta de Garmin.</div>
        <div id="nuMsg" style="margin-top:8px"></div>
      </div>` : ""}
      ${bk ? backupCard(bk) : ""}
      <div class="card wide" style="grid-column:1/-1"><h3>Historial de sincronizaciones</h3>
        <div class="table-wrap log" style="border:0"><table><thead><tr><th class="l">Inicio</th><th class="l">Estado</th><th class="l">Resultado</th></tr></thead>
        <tbody>${log.map((l) => `<tr><td class="l num">${esc((l.started || "").replace("T", " "))}</td><td class="l">${{ ok: '<span class="tag good">Correcta</span>', running: '<span class="tag accent">En curso</span>', auth: '<span class="tag bad">Sesión</span>', rate: '<span class="tag warn">Límite</span>' }[l.status] || '<span class="tag bad">Error</span>'}</td><td class="l">${esc(l.message || "")}</td></tr>`).join("") || `<tr><td colspan="3" class="muted">Todavía no ha habido sincronizaciones.</td></tr>`}</tbody></table></div>
      </div>
    </div>`;
  garminBox($("#garminBox"), st);
  $("#logoutBtn").onclick = logout;
  if (users) setupUserAdmin();
  if (bk) setupBackups(bk);
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

function fsize(b) {
  return b > 1024 ** 3 ? `${nf1.format(b / 1024 ** 3)} GB` : b > 1024 ** 2 ? `${nf1.format(b / 1024 ** 2)} MB` : `${nf0.format(b / 1024)} KB`;
}
function backupCard(bk) {
  const st = bk.settings, last = bk.backups[0];
  const kind = { auto: `<span class="tag">Automática</span>`, manual: `<span class="tag blue">Manual</span>`, "pre-restore": `<span class="tag warn">Antes de restaurar</span>` };
  return `<div class="card wide" style="grid-column:1/-1"><h3>Copias de seguridad ${st.enabled ? `<span class="tag good">Activadas</span>` : `<span class="tag bad">Desactivadas</span>`}</h3>
    <p class="muted" style="font-size:13px;margin-top:0">${last ? `Última copia ${esc(timeAgo(last.created))} (${fdate(last.created)} ${last.created.slice(11, 16)})` : "Todavía no hay copias"} ·
      ${bk.backups.length} ${bk.backups.length === 1 ? "copia" : "copias"}, ${fsize(bk.total_size)} en total${st.enabled && bk.state.next_run ? ` · próxima automática: ${esc(bk.state.next_run.replace("T", " "))}` : ""}</p>
    ${bk.state.last_error ? `<p class="tag bad" style="white-space:normal">Último error: ${esc(bk.state.last_error)}</p>` : ""}
    <div class="form-grid">
      <label class="check" style="align-self:end;padding-bottom:10px"><input type="checkbox" id="bkOn" ${st.enabled ? "checked" : ""}> Copia automática diaria</label>
      <label class="field">Hora<select id="bkHour">${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h === st.hour ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("")}</select></label>
      <label class="field">Diarias a conservar<input type="number" id="bkD" min="1" max="60" value="${st.keep_daily}"></label>
      <label class="field">Semanales<input type="number" id="bkW" min="0" max="52" value="${st.keep_weekly}"></label>
      <label class="field">Mensuales<input type="number" id="bkM" min="0" max="60" value="${st.keep_monthly}"></label>
    </div>
    <div class="row" style="margin-top:12px"><button class="btn" id="bkSave">Guardar ajustes</button><button class="btn primary" id="bkNow">Crear copia ahora</button>
      <label class="btn ghost" style="cursor:pointer">Restaurar desde archivo…<input type="file" id="bkUpload" accept=".gz,.db.gz" hidden></label></div>
    <div id="bkMsg" style="margin-top:8px"></div>
    ${bk.backups.length ? `<div class="table-wrap" style="border:0;margin-top:8px;max-height:360px;overflow:auto"><table>
      <thead><tr><th class="l">Fecha</th><th class="l">Tipo</th><th class="l">Versión</th><th>Tamaño</th><th></th></tr></thead>
      <tbody>${bk.backups.map((b) => `<tr>
        <td class="l num">${fdate(b.created)} ${b.created.slice(11, 16)}</td><td class="l">${kind[b.kind] || ""}</td>
        <td class="l faint">v${esc(b.version)}</td><td class="num">${fsize(b.size)}</td>
        <td><a class="btn small ghost" href="/api/admin/backups/${encodeURIComponent(b.name)}" download>Descargar</a>
          <button class="btn small ghost" data-bkrestore="${esc(b.name)}">Restaurar</button>
          <button class="btn small ghost" data-bkdel="${esc(b.name)}" style="color:var(--bad)">Borrar</button></td></tr>`).join("")}</tbody></table></div>` : ""}
    <p class="faint" style="font-size:12px;margin:10px 0 0">Las copias incluyen los datos de todos los usuarios y se guardan en la carpeta de datos de la app, en este mismo disco.
      Para protegerte de un fallo del disco, descarga de vez en cuando una copia a otro sitio. La clave que cifra las conexiones con Garmin no va dentro de la copia:
      si restauras en otro servidor, cada usuario tendrá que volver a conectar Garmin.</p>
  </div>`;
}

function setupBackups(bk) {
  const msg = (h) => ($("#bkMsg").innerHTML = h);
  $("#bkSave").onclick = async () => {
    try {
      await api("/api/admin/backups/settings", { method: "PUT", body: { enabled: $("#bkOn").checked, hour: +$("#bkHour").value,
        keep_daily: +$("#bkD").value, keep_weekly: +$("#bkW").value, keep_monthly: +$("#bkM").value } });
      toast("Ajustes de copias guardados"); rerender();
    } catch (e) { msg(`<p class="tag bad">${esc(e.message)}</p>`); }
  };
  $("#bkNow").onclick = async () => {
    const b = $("#bkNow"); b.disabled = true; b.textContent = "Creando copia…";
    try { const r = await api("/api/admin/backups", { method: "POST" }); toast(`Copia creada (${fsize(r.size)})`); rerender(); }
    catch (e) { msg(`<p class="tag bad">${esc(e.message)}</p>`); b.disabled = false; b.textContent = "Crear copia ahora"; }
  };
  const afterRestore = (r) => {
    msg(`<p class="tag good" style="white-space:normal">Copia restaurada: ${r.users} usuario(s), ${int(r.runs)} carreras. Se guardó antes una copia del estado anterior por si quieres deshacerlo. Recargando…</p>`);
    setTimeout(() => location.reload(), 2500);
  };
  const confirmRestore = (what) => {
    const t = prompt(`Vas a restaurar ${what}.\n\nTODOS los datos actuales de TODOS los usuarios se sustituirán por los de la copia (antes se guardará automáticamente una copia del estado actual). Puede que tengas que volver a iniciar sesión.\n\nEscribe RESTAURAR para confirmar:`);
    return t !== null && t.trim().toUpperCase() === "RESTAURAR";
  };
  $$("[data-bkrestore]").forEach((b) => (b.onclick = async () => {
    if (!confirmRestore(`la copia del ${b.closest("tr").children[0].textContent}`)) return;
    msg(`<p class="muted">Restaurando…</p>`);
    try { afterRestore(await api(`/api/admin/backups/${encodeURIComponent(b.dataset.bkrestore)}/restore`, { method: "POST" })); }
    catch (e) { msg(`<p class="tag bad" style="white-space:normal">${esc(e.message)}</p>`); }
  }));
  $("#bkUpload").onchange = async (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f || !confirmRestore(`el archivo «${f.name}»`)) return;
    const fd = new FormData(); fd.append("file", f);
    msg(`<p class="muted">Subiendo y comprobando la copia…</p>`);
    try { afterRestore(await api("/api/admin/backups-restore-upload", { method: "POST", body: fd })); }
    catch (err) { msg(`<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`); }
  };
  $$("[data-bkdel]").forEach((b) => (b.onclick = async () => {
    if (!confirm("¿Borrar esta copia de seguridad? No se puede deshacer.")) return;
    try { await api(`/api/admin/backups/${encodeURIComponent(b.dataset.bkdel)}`, { method: "DELETE" }); rerender(); }
    catch (e) { toast(e.message, true); }
  }));
}

function tempPassword() {
  // contraseña temporal legible: 4 grupos de 4 caracteres sin ambigüedades (0/O, 1/l)
  const abc = "abcdefghjkmnpqrstuvwxyz23456789";
  const rnd = crypto.getRandomValues(new Uint32Array(16));
  return [...rnd].map((n) => abc[n % abc.length]).join("").match(/.{4}/g).join("-");
}

function setupUserAdmin() {
  $("#nuGen").onclick = () => { $("#nuPass").value = tempPassword(); };
  $("#nu").onsubmit = async (e) => {
    e.preventDefault();
    const name = $("#nuName").value.trim(), pass = $("#nuPass").value;
    try {
      await api("/api/admin/users", { method: "POST", body: { username: name, password: pass, is_admin: $("#nuAdmin").checked } });
      await rerender();
      $("#nuMsg").innerHTML = `<p class="tag good" style="white-space:normal">Usuario <b>${esc(name)}</b> creado. Contraseña temporal: <b class="num">${esc(pass)}</b> (cópiala ahora; no se vuelve a mostrar).</p>`;
    } catch (err) { $("#nuMsg").innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`; }
  };
  $$("[data-reset]").forEach((b) => (b.onclick = async () => {
    const pass = tempPassword();
    if (!confirm(`¿Restablecer la contraseña de ${b.dataset.name}? Se cerrarán sus sesiones y tendrá que elegir una nueva al entrar.`)) return;
    try {
      await api(`/api/admin/users/${b.dataset.reset}/password`, { method: "POST", body: { password: pass } });
      await rerender();
      $("#nuMsg").innerHTML = `<p class="tag good" style="white-space:normal">Nueva contraseña temporal de <b>${esc(b.dataset.name)}</b>: <b class="num">${esc(pass)}</b> (cópiala ahora).</p>`;
    } catch (err) { toast(err.message, true); }
  }));
  $$("[data-mkadmin]").forEach((b) => (b.onclick = async () => {
    try { await api(`/api/admin/users/${b.dataset.mkadmin}/admin`, { method: "POST", body: { is_admin: b.dataset.val === "1" } }); rerender(); }
    catch (err) { toast(err.message, true); }
  }));
  $$("[data-del]").forEach((b) => (b.onclick = async () => {
    const name = b.dataset.name;
    const typed = prompt(`Se borrarán la cuenta de ${name} y TODOS sus datos (carreras, salud, ajustes). No se puede deshacer.\n\nEscribe "${name}" para confirmar:`);
    if (typed === null) return;
    if (typed.trim().toLowerCase() !== name.toLowerCase()) { toast("El nombre no coincide; no se ha eliminado nada.", true); return; }
    try { await api(`/api/admin/users/${b.dataset.del}`, { method: "DELETE" }); toast(`${name} eliminado`); rerender(); }
    catch (err) { toast(err.message, true); }
  }));
}

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
      <div class="auth-logo"><img class="logo" src="/static/icons/logo.svg" alt="" width="44" height="44"><span class="wordmark"><span class="wm-top">MODO</span><span class="wm-main">GUERRERO</span></span></div>
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
      if (ME.must_change) showForcedChange(); else enterApp();
    } catch (err) {
      msg.innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`;
      b.disabled = false;
    }
  };
}

function showForcedChange() {
  disposeAll();
  clearTimeout(refreshStatus._t);
  AUTHED = false;
  document.body.classList.add("auth-screen");
  $("#view").innerHTML = `
    <div class="auth-wrap"><div class="card auth-card">
      <div class="auth-logo"><img class="logo" src="/static/icons/logo.svg" alt="" width="44" height="44"><span class="wordmark"><span class="wm-top">MODO</span><span class="wm-main">GUERRERO</span></span></div>
      <h2>Elige tu contraseña</h2>
      <p class="muted">Hola${ME ? ", <b>" + esc(ME.username) + "</b>" : ""}. Estás usando una contraseña temporal; cámbiala por una que sólo sepas tú.</p>
      <form id="fc" class="form-grid" style="grid-template-columns:1fr">
        <input type="text" autocomplete="username" value="${esc(ME ? ME.username : "")}" hidden>
        <label class="field">Contraseña temporal<input type="password" id="fcCur" required autocomplete="current-password"></label>
        <label class="field">Nueva contraseña<input type="password" id="fcNew" required minlength="10" autocomplete="new-password"></label>
        <label class="field">Repite la nueva<input type="password" id="fcNew2" required minlength="10" autocomplete="new-password"></label>
        <button class="btn primary" style="justify-content:center">Guardar y entrar</button>
        <button type="button" class="btn ghost" id="fcOut" style="justify-content:center">Cerrar sesión</button>
        <div id="fcMsg"></div>
      </form>
    </div></div>`;
  $("#fcCur").focus();
  $("#fcOut").onclick = logout;
  $("#fc").onsubmit = async (e) => {
    e.preventDefault();
    const m = $("#fcMsg");
    if ($("#fcNew").value !== $("#fcNew2").value) { m.innerHTML = `<p class="tag bad">Las contraseñas no coinciden.</p>`; return; }
    try {
      await api("/api/account/password", { method: "POST", body: { current: $("#fcCur").value, new: $("#fcNew").value } });
      ME.must_change = false;
      toast("Contraseña guardada");
      enterApp();
    } catch (err) { m.innerHTML = `<p class="tag bad" style="white-space:normal">${esc(err.message)}</p>`; }
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

// ---------------------------------------------------------------- app instalada
const IS_STANDALONE = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
const IS_IOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
// Instalada no hay «tirar para recargar»: al volver a la app tras un rato, refrescar los datos
let hiddenAt = 0;
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { hiddenAt = Date.now(); return; }
  if (AUTHED && hiddenAt && Date.now() - hiddenAt > 5 * 60 * 1000) { rerender(); }
  hiddenAt = 0;
});

// ---------------------------------------------------------------- arranque
(async () => {
  try {
    const me = await api("/api/auth/me");
    $("#version").textContent = "v" + me.version;
    if (me.user) { ME = me.user; if (ME.must_change) showForcedChange(); else enterApp(); }
    else showAuth(me.setup_required);
  } catch (e) {
    $("#view").innerHTML = `<div class="empty"><h2>No se puede conectar con la app</h2><p>${esc(e.message)}</p></div>`;
  }
})();
