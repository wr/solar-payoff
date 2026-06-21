"use strict";

/* ---------- helpers ---------- */
const $ = (s) => document.querySelector(s);
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  let body = null;
  try { body = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((body && body.detail) || r.statusText);
  return body;
};
const usd = (n, dp = 0) =>
  n == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: dp, minimumFractionDigits: dp }).format(n);
const num = (n) => n == null ? "—" : new Intl.NumberFormat("en-US").format(Math.round(n));
const monthLabel = (m) => {
  const [y, mo] = m.split("-");
  return new Date(y, mo - 1, 1).toLocaleString("en-US", { month: "short", year: "2-digit" });
};
const monShort = (iso) => new Date(iso + "T00:00:00").toLocaleString("en-US", { month: "short", year: "numeric" });

let toastTimer;
function toast(msg, kind = "ok") {
  const t = $("#toast");
  t.textContent = msg; t.className = `toast show ${kind}`; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove("show"); }, 3200);
}

/* ---------- chart defaults ---------- */
Chart.defaults.color = "#4f6b80";
Chart.defaults.font.family = "'Hanken Grotesk', sans-serif";
Chart.defaults.font.size = 13;
const GRID = "rgba(15,42,60,0.08)";
const YEAR_SEP = "rgba(15,42,60,0.16)";
let climbChart, prodChart, billChart;

/* ---------- state ---------- */
let STATUS = null, PAYOFF = null;

async function loadAll() {
  try {
    [STATUS, PAYOFF] = await Promise.all([api("/api/status"), api("/api/payoff")]);
  } catch (e) {
    toast("Couldn't load data: " + e.message, "bad");
    return;
  }
  renderSync();
  renderSetup();
  renderHero();
  renderStats();
  renderCharts();
  renderWarranty();
  renderMethod();
  populateSettings();
  renderEnphaseStatus();
}

/* ---------- sync state in topbar ---------- */
function renderSync() {
  const e = STATUS.enphase;
  const el = $("#syncState");
  if (!e.connected) { el.textContent = "not connected"; return; }
  if (e.last_sync) {
    el.textContent = "synced " + timeAgo(e.last_sync);
  } else { el.textContent = "connected"; }
}
function timeAgo(iso) {
  const d = new Date(iso.replace(" ", "T"));
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return mins + "m ago";
  const h = Math.floor(mins / 60);
  if (h < 24) return h + "h ago";
  return Math.floor(h / 24) + "d ago";
}

/* ---------- setup banner ---------- */
function renderSetup() {
  const e = STATUS.enphase, d = STATUS.data;
  const netCost = PAYOFF.headline.net_install_cost;
  const rateSet = parseFloat(STATUS.financials.electricity_rate) > 0;
  const steps = [
    { done: e.creds_set, txt: "Add Enphase API credentials", act: "creds" },
    { done: e.connected, txt: "Connect your Enphase account", act: "enphase" },
    { done: netCost > 0 && rateSet, txt: "Enter system cost, switch-on date & electricity rate", act: "financials" },
    { done: d.utility_days > 0, txt: "Upload your Eversource Green Button export (optional, sharpens accuracy)", act: "gb" },
  ];
  const allCore = steps.slice(0, 3).every((s) => s.done);
  const banner = $("#setupBanner");
  banner.hidden = allCore && steps[3].done;
  $("#setupSteps").innerHTML = steps.map((s, i) =>
    `<li class="${s.done ? "done" : ""}"><span class="n">${s.done ? "✓" : i + 1}</span>
      <span>${s.txt} ${s.done ? "" : `· <a data-open="${s.act}">open</a>`}</span></li>`
  ).join("");
  document.querySelectorAll("#setupSteps a[data-open]").forEach((a) =>
    a.addEventListener("click", () => openDrawer()));
}

/* ---------- hero ---------- */
function renderHero() {
  const h = PAYOFF.headline;
  const pct = h.pct_paid;
  $("#pctPaid").textContent = pct == null ? "—" : Math.min(pct, 100).toFixed(0) + "%";
  drawGauge(pct == null ? 0 : Math.max(0, Math.min(pct / 100, 1)));

  $("#recovered").textContent = usd(h.total_saved);
  $("#remaining").textContent = h.already_paid_off ? "Paid off 🎉" : usd(h.remaining);
  $("#netCost").textContent = usd(h.net_install_cost);
  $("#payoffPeriod").textContent = h.payoff_years ? `${h.payoff_years} yrs` : "—";

  const beEl = $("#breakevenDate"), subEl = $("#breakevenSub");
  if (h.net_install_cost <= 0) {
    beEl.textContent = "Set cost"; subEl.textContent = "Add your install cost in Setup";
  } else if (h.already_paid_off) {
    beEl.textContent = h.breakeven_date ? monShort(h.breakeven_date) : "Done";
    subEl.textContent = "Already paid off 🎉";
  } else if (h.breakeven_date) {
    beEl.textContent = monShort(h.breakeven_date);
    subEl.textContent = "";
  } else {
    beEl.textContent = "—"; subEl.textContent = "Need production data to project";
  }
}

const GA = { cx: 160, cy: 170, r: 140 };
let gaugeRAF = null;
// the sun is static markup now (a bordered disc) — see #sun in index.html
function setGauge(p) {
  const arcLen = Math.PI * GA.r;
  const fill = $("#arcFill");
  fill.style.strokeDasharray = arcLen;
  fill.style.strokeDashoffset = arcLen * (1 - p);     // fill grows along the arc
  const theta = Math.PI + p * Math.PI;                // sun rides the arc, not a straight line
  const x = GA.cx + GA.r * Math.cos(theta), y = GA.cy + GA.r * Math.sin(theta);
  $("#sun").setAttribute("transform", `translate(${x.toFixed(2)},${y.toFixed(2)})`);
}
function drawGauge(target) {
  const dPath = `M ${GA.cx - GA.r} ${GA.cy} A ${GA.r} ${GA.r} 0 0 1 ${GA.cx + GA.r} ${GA.cy}`;
  $("#arcTrack").setAttribute("d", dPath);
  $("#arcFill").setAttribute("d", dPath);
  if (gaugeRAF) cancelAnimationFrame(gaugeRAF);
  const dur = 1300, t0 = performance.now(), ease = (x) => 1 - Math.pow(1 - x, 3);
  setGauge(0);
  (function frame(now) {
    const k = Math.min((now - t0) / dur, 1);
    setGauge(target * ease(k));
    if (k < 1) gaugeRAF = requestAnimationFrame(frame);
  })(t0);
}

/* ---------- stats ---------- */
function renderStats() {
  const h = PAYOFF.headline;
  const mwh = h.lifetime_production_kwh >= 1000;
  const co2t = h.co2_avoided_kg >= 1000;
  const ann = h.avg_annual_production_kwh, annMwh = ann && ann >= 1000;
  const cards = [
    { label: "Lifetime production", val: mwh ? (h.lifetime_production_kwh / 1000).toFixed(1) : num(h.lifetime_production_kwh), unit: mwh ? "MWh" : "kWh", sub: h.first_date ? `since ${monShort(h.first_date)}` : "" },
    { label: "Yearly production", val: ann == null ? "—" : (annMwh ? (ann / 1000).toFixed(2) : num(ann)), unit: annMwh ? "MWh/yr" : "kWh/yr", sub: h.avg_power_w ? `≈ ${num(h.avg_power_w)} W average` : "" },
    { label: "Energy offset", val: h.pct_offset == null ? "—" : num(h.pct_offset), unit: "%", sub: "solar vs. your usage" },
    { label: "Performance", val: h.performance_pct == null ? "—" : h.performance_pct, unit: "%", sub: h.pv_expected_annual_kwh ? `of PVWatts expected (${num(h.pv_expected_annual_kwh)} kWh/yr)` : "vs expected" },
    { label: "Clear-sky capture", val: h.clearsky_capture_pct == null ? "—" : h.clearsky_capture_pct, unit: "%", sub: "actual vs. ideal-weather max" },
    { label: "Avg. monthly savings", val: usd(h.avg_monthly_savings), unit: "", sub: `≈ ${usd(h.avg_daily_savings)}/day` },
    { label: "CO₂ avoided", val: co2t ? (h.co2_avoided_kg / 1000).toFixed(1) : num(h.co2_avoided_kg), unit: co2t ? "tonnes" : "kg", sub: "vs grid average" },
    { label: "Days producing", val: num(h.days_elapsed), unit: "days", sub: h.last_date ? `latest ${monShort(h.last_date)}` : "" },
  ];
  $("#stats").innerHTML = cards.map((c) =>
    `<div class="stat">
      <span class="s-label"><span class="s-dot"></span>${c.label}</span>
      <span><span class="s-val">${c.val}</span> <span class="s-unit">${c.unit}</span></span>
      <span class="s-sub">${c.sub}</span>
    </div>`).join("");
}

/* ---------- warranty ---------- */
function renderWarranty() {
  const w = PAYOFF.warranty || [];
  const panel = $("#warrantyPanel");
  if (!w.length) { panel.hidden = true; return; }
  panel.hidden = false;
  $("#warrantyGrid").innerHTML = w.map((x) => {
    const exp = new Date(x.expires + "T00:00:00").getFullYear();
    const expired = x.remaining_years <= 0;
    const sub = expired ? `expired ${exp}` : `${x.remaining_years} yrs left · through ${exp}`;
    return `<div class="warranty-item">
      <div class="w-top"><span class="w-name">${x.name}</span><span class="w-term">${x.term}-yr</span></div>
      <div class="w-bar"><div class="w-fill ${expired ? "expired" : ""}" style="width:${Math.round(x.pct_left * 100)}%"></div></div>
      <div class="w-sub">${sub}</div>
    </div>`;
  }).join("");
}

/* ---------- charts ---------- */
function lastPerMonth(series, valKey) {
  const map = {};
  series.forEach((d) => { map[d.date.slice(0, 7)] = d[valKey]; });
  return map;
}
function renderCharts() {
  const h = PAYOFF.headline;
  const netCost = h.net_install_cost;

  // ----- climb chart -----
  const actMap = lastPerMonth(PAYOFF.cumulative, "cumulative_savings");
  const projMap = lastPerMonth(PAYOFF.projection, "cumulative_savings");
  const months = [...new Set([...Object.keys(actMap), ...Object.keys(projMap)])].sort();
  const actData = months.map((m) => actMap[m] ?? null);
  const projData = months.map((m) => projMap[m] ?? null);
  const costData = months.map(() => netCost > 0 ? netCost : null);

  if (climbChart) climbChart.destroy();
  const ctx = $("#climbChart").getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 320);
  grad.addColorStop(0, "rgba(255,150,40,0.35)");
  grad.addColorStop(1, "rgba(255,150,40,0.01)");
  climbChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: months,
      datasets: [
        { label: "Saved so far", data: actData, borderColor: "#ffac3b", backgroundColor: grad, fill: true, tension: 0.3, borderWidth: 2.5, pointRadius: 0, spanGaps: false },
        { label: "Projection", data: projData, borderColor: "rgba(255,172,59,0.6)", borderDash: [6, 5], fill: false, tension: 0.2, borderWidth: 2, pointRadius: 0, spanGaps: true },
        { label: "System cost", data: costData, borderColor: "#1f8fc4", borderDash: [2, 4], fill: false, borderWidth: 1.5, pointRadius: 0 },
      ],
    },
    options: baseOpts({ money: true, months }),
  });

  // ----- production chart -----
  const pm = PAYOFF.monthly.map((m) => m.month);
  if (prodChart) prodChart.destroy();
  prodChart = new Chart($("#prodChart"), {
    type: "bar",
    data: { labels: pm, datasets: [
      { label: "Production (kWh)", data: PAYOFF.monthly.map((m) => m.production_kwh),
        backgroundColor: "rgba(255,172,59,0.78)", hoverBackgroundColor: "#ffc24d", borderRadius: 4 },
    ]},
    options: baseOpts({ unit: " kWh", months: pm }),
  });

  // ----- bill chart (stacked: what you pay + what solar saved = no-solar bill) -----
  if (billChart) billChart.destroy();
  billChart = new Chart($("#billChart"), {
    type: "bar",
    data: { labels: pm, datasets: [
      { label: "You paid", data: PAYOFF.monthly.map((m) => m.actual_cost),
        backgroundColor: "rgba(224,95,58,0.92)", borderRadius: 3, stack: "bill" },
      { label: "Solar saved", data: PAYOFF.monthly.map((m) => m.savings),
        backgroundColor: "rgba(31,169,104,0.92)", borderRadius: 3, stack: "bill" },
    ]},
    options: baseOpts({ money: true, stacked: true, legend: true, months: pm }),
  });
}

function baseOpts({ money = false, unit = "", stacked = false, legend = false, months = null } = {}) {
  const fmt = (v) => money ? usd(v) : num(v) + unit;
  // x-axis: whole-year labels with a vertical separator at each year boundary
  const xScale = months ? {
    stacked,
    grid: {
      drawTicks: false,
      color: months.map((m) => m.endsWith("-01") ? YEAR_SEP : "transparent"),
      lineWidth: months.map((m) => m.endsWith("-01") ? 1 : 0),
    },
    ticks: {
      autoSkip: false, maxRotation: 0, font: { size: 12.5 },
      callback: (val, idx) => {
        const m = months[idx];
        if (!m) return "";
        const [y, mo] = m.split("-");
        return (mo === "01" || idx === 0) ? y : "";
      },
    },
  } : { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }, stacked };

  return {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: legend ? { display: true, labels: { boxWidth: 12, boxHeight: 12, usePointStyle: true, padding: 16, font: { size: 13 } } } : { display: false },
      tooltip: {
        backgroundColor: "#11293a", borderColor: "rgba(255,255,255,0.12)", borderWidth: 1,
        titleColor: "#ffffff", bodyColor: "#cfe0ec", padding: 11, cornerRadius: 9, usePointStyle: true,
        titleFont: { size: 13 }, bodyFont: { size: 13 },
        callbacks: {
          title: (items) => (items[0] && months) ? monthLabel(items[0].label) : (items[0] ? items[0].label : ""),
          label: (c) => ` ${c.dataset.label}: ${c.parsed.y == null ? "—" : fmt(c.parsed.y)}`,
        },
      },
    },
    scales: {
      x: xScale,
      y: { grid: { color: GRID }, ticks: { callback: (v) => money ? "$" + num(v) : num(v) }, stacked, beginAtZero: true },
    },
  };
}

/* ---------- method note ---------- */
function renderMethod() {
  const h = PAYOFF.headline;
  const tou = (h.rate_on_avg && h.rate_off_avg)
    ? ` at your <b>time-of-use</b> rates (on-peak avg $${h.rate_on_avg}, off-peak avg $${h.rate_off_avg}/kWh)`
    : "";
  const split = h.onpeak_calibrated
    ? `split on/off-peak from your actual 15-min generation against the 12–8pm Mon–Fri window`
    : `split on/off-peak by when you generated (estimated from export timing)`;
  $("#method").innerHTML =
    `<b>Method:</b> avoided cost = your solar production valued${tou}, ${split}, ` +
    `summed over each real Eversource billing cycle (${h.n_bills} statements). ` +
    `<b>Fixed customer charges are excluded</b> — you'd pay those with or without solar. ` +
    `Effective value of solar ranges <b>$${h.rate_min}–$${h.rate_max}/kWh</b> (avg $${h.rate_avg}). ` +
    `Breakeven projects your recent pace forward; adjust anything in Setup.`;
}

/* ---------- settings drawer ---------- */
function openDrawer() { $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false"); $("#scrim").hidden = false; }
function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#scrim").hidden = true; }

function populateSettings() {
  const f = STATUS.financials;
  $("#f_gross").value = f.install_cost_gross && f.install_cost_gross !== "0" ? f.install_cost_gross : "";
  $("#f_incentives").value = f.incentives && f.incentives !== "0" ? f.incentives : "";
  $("#f_switchon").value = f.switchon_date || "";
  $("#f_rate").value = f.electricity_rate || "";
  $("#f_export").value = f.export_rate || "";
  $("#f_wpanel").value = f.panel_warranty_yr || "";
  $("#f_winv").value = f.inverter_warranty_yr || "";
  $("#f_wwork").value = f.workmanship_warranty_yr || "";
  const rm = f.rate_mode || "flat";
  document.querySelectorAll("#rateModeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === rm));
  $("#touFields").hidden = rm !== "tou";
  $("#f_tou_on").value = f.tou_on_rate || "";
  $("#f_tou_off").value = f.tou_off_rate || "";
  $("#f_onpeak_start").value = f.onpeak_start || "";
  $("#f_onpeak_end").value = f.onpeak_end || "";
  $("#f_onpeak_days").value = f.onpeak_days || "weekdays";
  $("#f_pv_lat").value = f.pv_lat || "";
  $("#f_pv_lon").value = f.pv_lon || "";
  $("#f_pv_tilt").value = f.pv_tilt || "";
  $("#f_pv_azimuth").value = f.pv_azimuth || "";
  $("#f_nlr_key").value = f.nlr_api_key || "";
  updateNet();
  document.querySelectorAll("#metricSeg button").forEach((b) =>
    b.classList.toggle("on", b.dataset.metric === (f.payoff_metric || "avoided_cost")));
  const h = PAYOFF.headline;
  const hint = $("#rateHint");
  hint.textContent = h.rate_min != null
    ? `Real rate from your bills: $${h.rate_min}–$${h.rate_max}/kWh (avg $${h.rate_avg}). This fallback only applies to months with no bill.`
    : "No bills yet — this rate is used for everything until you upload some.";
  hint.style.cursor = "default";
}
function updateNet() {
  const g = parseFloat($("#f_gross").value) || 0;
  const i = parseFloat($("#f_incentives").value) || 0;
  $("#f_net").textContent = usd(Math.max(g - i, 0));
}

function renderEnphaseStatus() {
  const e = STATUS.enphase;
  const el = $("#enphaseStatus");
  let html = "";
  if (e.connected) {
    html += `<div><span class="ok">● Connected</span>${e.system_name ? ` — <b>${e.system_name}</b>` : ""}</div>`;
    if (e.last_sync) html += `<div>Last sync: ${e.last_sync.replace("T", " ")}</div>`;
    $("#enphaseConnect").style.display = "none";
  } else {
    html += e.creds_set ? `<div>Credentials set, not yet linked.</div>` : `<div class="bad">● Add API credentials below first.</div>`;
    $("#enphaseConnect").style.display = e.creds_set ? "block" : "none";
  }
  if (e.last_sync_error) html += `<div class="bad small">⚠ ${e.last_sync_error}</div>`;
  el.innerHTML = html;
}

/* ---------- actions ---------- */
async function saveFinancials() {
  const body = {
    install_cost_gross: $("#f_gross").value || "0",
    incentives: $("#f_incentives").value || "0",
    switchon_date: $("#f_switchon").value || "",
    electricity_rate: $("#f_rate").value || "0",
    export_rate: $("#f_export").value || "",
    payoff_metric: document.querySelector("#metricSeg button.on").dataset.metric,
    panel_warranty_yr: $("#f_wpanel").value || "25",
    inverter_warranty_yr: $("#f_winv").value || "25",
    workmanship_warranty_yr: $("#f_wwork").value || "25",
    rate_mode: document.querySelector("#rateModeSeg button.on").dataset.mode,
    tou_on_rate: $("#f_tou_on").value || "",
    tou_off_rate: $("#f_tou_off").value || "",
    onpeak_start: $("#f_onpeak_start").value || "12",
    onpeak_end: $("#f_onpeak_end").value || "20",
    onpeak_days: $("#f_onpeak_days").value || "weekdays",
    pv_lat: $("#f_pv_lat").value || "",
    pv_lon: $("#f_pv_lon").value || "",
    pv_tilt: $("#f_pv_tilt").value || "",
    pv_azimuth: $("#f_pv_azimuth").value || "",
    nlr_api_key: $("#f_nlr_key").value || "",
  };
  try {
    await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    toast("Saved");
    await loadAll();
  } catch (e) { toast("Save failed: " + e.message, "bad"); }
}

async function fetchPvwatts(btn) {
  const orig = btn.textContent; btn.disabled = true; btn.textContent = "Fetching…";
  try {
    await saveFinancials();   // persist location/array first (also reloads)
    const r = await api("/api/pvwatts/fetch", { method: "POST" });
    $("#pvwattsResult").innerHTML = `<span class="ok">✓ Expected ${num(r.expected_annual_kwh)} kWh/yr</span> — Performance card updated.`;
    toast("PVWatts updated");
    await loadAll();
  } catch (e) {
    $("#pvwattsResult").innerHTML = `<span class="bad">${e.message}</span>`;
    toast("PVWatts failed: " + e.message, "bad");
  } finally { btn.disabled = false; btn.textContent = orig; }
}

async function saveCreds() {
  const body = {
    api_key: $("#c_key").value || null,
    client_id: $("#c_id").value || null,
    client_secret: $("#c_secret").value || null,
    system_id: $("#c_sys").value || null,
  };
  try {
    await api("/api/enphase/credentials", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    toast("Credentials saved");
    ["#c_key", "#c_id", "#c_secret"].forEach((s) => ($(s).value = ""));
    await loadAll();
  } catch (e) { toast("Failed: " + e.message, "bad"); }
}

async function startEnphaseAuth() {
  try {
    const { url } = await api("/api/enphase/authorize-url");
    window.open(url, "_blank", "noopener");
    $("#codeRow").hidden = false;
    toast("Authorize in the new window, then paste the code");
  } catch (e) { toast(e.message, "bad"); }
}
async function linkEnphase() {
  const code = $("#enphaseCode").value.trim();
  if (!code) { toast("Paste the code first", "bad"); return; }
  $("#enphaseLinkBtn").disabled = true;
  try {
    await api("/api/enphase/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
    toast("Enphase connected & synced ☀");
    $("#enphaseCode").value = "";
    await loadAll();
  } catch (e) { toast("Link failed: " + e.message, "bad"); }
  finally { $("#enphaseLinkBtn").disabled = false; }
}
async function syncNow(btn) {
  const orig = btn.textContent; btn.disabled = true; btn.textContent = "Syncing…";
  try { const r = await api("/api/enphase/sync", { method: "POST" }); toast(`Synced — ${r.result.days_production} days of data`); await loadAll(); }
  catch (e) { toast("Sync failed: " + e.message, "bad"); }
  finally { btn.disabled = false; btn.textContent = orig; }
}

/* green button upload */
let gbFile = null;
function setGbFile(f) {
  gbFile = f;
  $("#dropLabel").textContent = f ? f.name : "Choose or drop a file";
  $("#uploadBtn").disabled = !f;
}
async function uploadGb() {
  if (!gbFile) return;
  const fd = new FormData(); fd.append("file", gbFile);
  $("#uploadBtn").disabled = true;
  try {
    const r = await api("/api/greenbutton/upload", { method: "POST", body: fd });
    const s = r.summary;
    $("#gbResult").innerHTML = `<span class="ok">✓ Imported ${s.days} days</span> (${s.first} → ${s.last}), ${num(s.total_kwh)} kWh${s.has_cost ? ", with costs" : " (no $ in file — using your rate)"}.`;
    toast("Green Button imported");
    setGbFile(null); $("#gbFile").value = "";
    await loadAll();
  } catch (e) { $("#gbResult").innerHTML = `<span class="bad">${e.message}</span>`; toast("Upload failed", "bad"); }
  finally { $("#uploadBtn").disabled = !gbFile; }
}

/* ---------- wire up ---------- */
function wire() {
  $("#settingsBtn").addEventListener("click", openDrawer);
  $("#drawerClose").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  $("#refreshBtn").addEventListener("click", (e) => syncNow(e.currentTarget));
  $("#syncNow2").addEventListener("click", (e) => syncNow(e.currentTarget));
  $("#saveFinancials").addEventListener("click", saveFinancials);
  $("#saveCreds").addEventListener("click", saveCreds);
  $("#enphaseAuthBtn").addEventListener("click", startEnphaseAuth);
  $("#enphaseLinkBtn").addEventListener("click", linkEnphase);
  $("#f_gross").addEventListener("input", updateNet);
  $("#f_incentives").addEventListener("input", updateNet);
  $("#rateHint").addEventListener("click", () => {
    if (PAYOFF && PAYOFF.headline.rate_avg) $("#f_rate").value = PAYOFF.headline.rate_avg;
  });
  document.querySelectorAll("#metricSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#metricSeg button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
    }));
  document.querySelectorAll("#rateModeSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#rateModeSeg button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      $("#touFields").hidden = b.dataset.mode !== "tou";
    }));
  $("#pvwattsBtn").addEventListener("click", (e) => fetchPvwatts(e.currentTarget));

  // file input + drag/drop
  const dz = $("#dropzone");
  $("#gbFile").addEventListener("change", (e) => setGbFile(e.target.files[0]));
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) setGbFile(e.dataTransfer.files[0]); });
  $("#uploadBtn").addEventListener("click", uploadGb);

  // open drawer if redirected back from oauth callback
  const params = new URLSearchParams(location.search);
  if (params.get("enphase") === "connected") toast("Enphase connected ☀");
  if (params.get("enphase") === "error") toast("Enphase connection failed", "bad");
}

wire();
loadAll();
