let instrument = "NIFTY";
let authToken = localStorage.getItem("oi_auth_token") || "";
let currentUser = localStorage.getItem("oi_username") || "";
let latestSnapshot = null;
let frontendEnv = {};
let activeHistoryId = "";
let aiEnabled = false;
let csvType = "chain";
let currentAnalysisId = "";
let currentFileName = "";
let savePromise = Promise.resolve();
let currentView = "live";
let newsInstrument = "NIFTY";
let newsLoading = false;
let newsLoaded = {};
let newsFilter = "";
let lastNews = null;
let liveLoading = false;
let liveLoaded = false;
let liveAutoRefresh = true;
let liveTimer = null;
let liveWindowKey = localStorage.getItem("oi_live_window_key") || "3m";
let brightMode = localStorage.getItem("oi_bright_mode") === "1";

const LIVE_REFRESH_MS = 30000;
document.documentElement.classList.toggle("bright-mode", brightMode);

const CONFIG = window.OI_ANALYZER_CONFIG || {};
const STRIKE_RANGE = {
  NIFTY: { min: 15000, max: 35000 },
  BANKNIFTY: { min: 30000, max: 90000 },
};

document.addEventListener("DOMContentLoaded", async () => {
  frontendEnv = await loadFrontendEnv();
  initClock();
  applyThemeMode();
  bindLogin();
  bindUpload();
  bindActions();

  if (authToken) {
    showApp();
    checkBackend();
    loadHistory();
  } else {
    showLogin();
  }
});

function getApiBase() {
  const explicitEnvBase = frontendEnv.BACKEND_BASE_URL || frontendEnv.FRONTEND_API_BASE_URL;
  if (explicitEnvBase) return explicitEnvBase.replace(/\/$/, "");

  const host = window.location.hostname;
  const isLocalFrontend =
    host === "localhost" ||
    host === "127.0.0.1" ||
    host === "" ||
    host.startsWith("192.168.") ||
    host.startsWith("10.") ||
    host.endsWith(".local");
  if (isLocalFrontend) return "http://localhost:10000";

  return (
    CONFIG.apiBaseUrl ||
    "http://localhost:10000"
  ).replace(/\/$/, "");
}

async function loadFrontendEnv() {
  try {
    const res = await fetch(".env", { cache: "no-store" });
    if (!res.ok) return {};
    const text = await res.text();
    return text.split("\n").reduce((env, line) => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) return env;
      const [key, ...rest] = trimmed.split("=");
      env[key.trim()] = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
      return env;
    }, {});
  } catch (error) {
    return {};
  }
}

function apiUrl(path) {
  return `${getApiBase()}${path}`;
}

function authHeaders(extra = {}) {
  return {
    ...extra,
    Authorization: `Bearer ${authToken}`,
  };
}

function initClock() {
  const tick = () => {
    const ist = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    const p = (n) => String(n).padStart(2, "0");
    document.getElementById("clockEl").textContent =
      `${p(ist.getHours())}:${p(ist.getMinutes())}:${p(ist.getSeconds())} IST`;
  };
  tick();
  setInterval(tick, 1000);
}

function bindLogin() {
  document.getElementById("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorEl = document.getElementById("loginError");
    errorEl.textContent = "";

    const username = document.getElementById("loginUsername").value.trim();
    const password = document.getElementById("loginPassword").value;

    try {
      const res = await fetch(apiUrl("/api/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await readApiJson(res);
      if (!res.ok) throw new Error(data.error || "Login failed.");

      authToken = data.token;
      currentUser = data.username;
      localStorage.setItem("oi_auth_token", authToken);
      localStorage.setItem("oi_username", currentUser);
      document.getElementById("loginPassword").value = "";
      showApp();
      checkBackend();
      loadHistory();
    } catch (error) {
      errorEl.textContent = getLoginErrorMessage(error);
    }
  });
}

function getLoginErrorMessage(error) {
  if (error instanceof TypeError) {
    return "Server unreachable. Please try again in a moment.";
  }
  return error.message || "Login failed.";
}

function bindActions() {
  document.getElementById("logoutBtn").addEventListener("click", logout);
  document.getElementById("themeToggleBtn")?.addEventListener("click", () => {
    brightMode = !brightMode;
    localStorage.setItem("oi_bright_mode", brightMode ? "1" : "0");
    applyThemeMode();
  });
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });
  document.getElementById("liveRefreshBtn").addEventListener("click", () => loadLiveOptions(true));
  document.getElementById("liveAutoToggle").addEventListener("change", (event) => {
    liveAutoRefresh = event.target.checked;
    const state = document.getElementById("liveAutoState");
    state.textContent = liveAutoRefresh ? "On" : "Off";
    state.className = liveAutoRefresh ? "bull" : "";
    scheduleLiveRefresh();
  });
  document.querySelectorAll("#newsView [data-inst]").forEach((btn) => {
    btn.addEventListener("click", () => {
      newsInstrument = btn.dataset.inst;
      document.getElementById("newsTabNifty").classList.toggle("active", newsInstrument === "NIFTY");
      document.getElementById("newsTabBank").classList.toggle("active", newsInstrument === "BANKNIFTY");
      loadNews();
    });
  });
  document.getElementById("newsFetchBtn").addEventListener("click", () => loadNews(true));
  document.getElementById("refreshHistoryBtn").addEventListener("click", loadHistory);
  document.getElementById("typeChain").addEventListener("click", () => setCsvType("chain"));
  document.getElementById("typeStrike").addEventListener("click", () => setCsvType("strike"));
  document.getElementById("aiToggle").addEventListener("change", (event) => {
    aiEnabled = event.target.checked;
    const state = document.getElementById("aiToggleState");
    state.textContent = aiEnabled ? "On" : "Off";
    state.className = aiEnabled ? "bull" : "";
  });
  document.getElementById("uploadNewBtn").addEventListener("click", () => {
    const input = document.getElementById("fileInput");
    input.value = "";
    input.click();
  });
}

function applyThemeMode() {
  document.documentElement.classList.toggle("bright-mode", brightMode);
  const btn = document.getElementById("themeToggleBtn");
  if (btn) {
    btn.textContent = brightMode ? "Dark" : "Bright";
    btn.title = brightMode ? "Switch to dark mode" : "Switch to bright mode";
  }
}

function setLiveWindow(key) {
  liveWindowKey = key;
  localStorage.setItem("oi_live_window_key", key);
  if (window.lastLiveOptionsData) {
    renderLiveOptions(window.lastLiveOptionsData);
  }
}

function openKiteLogin() {
  window.open(apiUrl("/api/kite/login"), "_blank", "noopener,noreferrer,width=900,height=760");
}

function bindUpload() {
  const dz = document.getElementById("dropZone");
  dz.addEventListener("dragover", (event) => {
    event.preventDefault();
    dz.classList.add("drag");
  });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (event) => {
    event.preventDefault();
    dz.classList.remove("drag");
    handleFile(event.dataTransfer.files[0]);
  });
  document.getElementById("fileInput").addEventListener("change", (event) => {
    handleFile(event.target.files[0]);
  });
}

function setView(view) {
  currentView = view;
  document.getElementById("liveView").classList.toggle("hidden", view !== "live");
  document.getElementById("appView").classList.toggle("hidden", view !== "oi");
  document.getElementById("newsView").classList.toggle("hidden", view !== "news");
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });
  if (view === "live" && !liveLoaded) loadLiveOptions();
  if (view === "news" && !newsLoaded[newsInstrument]) loadNews();
  scheduleLiveRefresh();
}

function showLogin() {
  document.getElementById("loginView").classList.remove("hidden");
  document.getElementById("liveView").classList.add("hidden");
  document.getElementById("appView").classList.add("hidden");
  document.getElementById("newsView").classList.add("hidden");
  document.getElementById("mainNav").classList.add("hidden");
  document.getElementById("logoutBtn").classList.add("hidden");
  document.getElementById("userPill").textContent = "Not logged in";
  scheduleLiveRefresh();
}

function showApp() {
  document.getElementById("loginView").classList.add("hidden");
  document.getElementById("mainNav").classList.remove("hidden");
  setView(currentView);
  document.getElementById("logoutBtn").classList.remove("hidden");
  document.getElementById("userPill").textContent = currentUser || "Logged in";
}

function logout() {
  authToken = "";
  currentUser = "";
  localStorage.removeItem("oi_auth_token");
  localStorage.removeItem("oi_username");
  reset();
  currentView = "live";
  liveLoaded = false;
  newsLoaded = {};
  document.getElementById("liveBody").innerHTML =
    '<div class="empty-state">Loading live NIFTY options intelligence from Kite...</div>';
  document.getElementById("newsBody").innerHTML =
    '<div class="empty-state">Click <strong>Fetch Latest News</strong> to load headlines and a sentiment score.</div>';
  setView("live");
  showLogin();
}

async function checkBackend() {
  const el = document.getElementById("backendStatus");
  el.textContent = "Checking";
  try {
    const res = await fetch(apiUrl("/health"));
    if (!res.ok) throw new Error("Health check failed");
    el.textContent = "Online";
    el.className = "bull";
  } catch (error) {
    el.textContent = "Offline";
    el.className = "warn";
  }
}

function setInstrument(inst) {
  instrument = inst;
  document.getElementById("tabNifty").classList.toggle("active", inst === "NIFTY");
  document.getElementById("tabBankNifty").classList.toggle("active", inst === "BANKNIFTY");
  updateUploadSub();
}

function setCsvType(type) {
  csvType = type;
  document.getElementById("typeChain").classList.toggle("active", type === "chain");
  document.getElementById("typeStrike").classList.toggle("active", type === "strike");
  document.getElementById("strikeField").classList.toggle("hidden", type !== "strike");
  updateUploadSub();
}

function updateUploadSub() {
  const name = instrument === "NIFTY" ? "Nifty 50" : "Bank Nifty";
  document.getElementById("uploadSub").textContent = csvType === "strike"
    ? `${name} single-strike CSV (one strike, all expiries) from NSE`
    : `${name} options-chain CSV (all strikes, one expiry) from NSE`;
}

function handleFile(file) {
  if (!authToken) {
    showLogin();
    return;
  }
  if (!file || !file.name.toLowerCase().endsWith(".csv")) {
    alert("Please upload a CSV file from NSE.");
    return;
  }
  const reader = new FileReader();
  reader.onload = (event) => {
    activeHistoryId = "";
    markActiveHistory();
    currentFileName = file.name;
    if (!parseCSV(event.target.result, file.name)) return;
    const name = instrument === "NIFTY" ? "Nifty 50" : "Bank Nifty";
    const strikePart = csvType === "strike" ? ` · Strike ${latestSnapshot.levels.strike.toLocaleString()}` : "";
    setSource(`${name}${strikePart} · ${file.name}`);
  };
  reader.readAsText(file);
}

function parseCSVRow(line) {
  const cols = [];
  let cur = "";
  let inQ = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQ && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQ = !inQ;
      }
    } else if (ch === "," && !inQ) {
      cols.push(cur.trim());
      cur = "";
    } else {
      cur += ch;
    }
  }
  cols.push(cur.trim());
  return cols;
}

function numVal(s) {
  if (!s || s === "-") return 0;
  return parseFloat(String(s).replace(/,/g, "")) || 0;
}

function detectCsvType(lines) {
  for (const line of lines.slice(0, 6)) {
    const up = line.toUpperCase();
    if (up.includes("EXPIRY DATE")) return "strike";
    if (up.includes("STRIKE") && (up.includes(",OI,") || up.includes("VOLUME"))) return "chain";
  }
  return null;
}

function parseCSV(text, fileName = "") {
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  const detected = detectCsvType(lines);
  if (detected && detected !== csvType) setCsvType(detected);
  return csvType === "strike" ? parseStrikeCSV(lines, fileName) : parseChainCSV(lines);
}

function parseChainCSV(lines) {
  let headerIdx = lines.findIndex((line) => {
    const up = line.toUpperCase();
    return up.includes("STRIKE") && (up.includes(",OI,") || up.includes("VOLUME"));
  });
  if (headerIdx === -1) headerIdx = 1;

  const headers = parseCSVRow(lines[headerIdx] || "").map((h) => h.toUpperCase().trim());
  let strikeCol = headers.indexOf("STRIKE");
  if (strikeCol === -1) strikeCol = headers.findIndex((h) => h.includes("STRIKE"));

  const rows = [];
  let totalCallOI = 0;
  let totalPutOI = 0;
  const sr = STRIKE_RANGE[instrument];
  const otherInst = instrument === "NIFTY" ? "BANKNIFTY" : "NIFTY";
  const otherRange = STRIKE_RANGE[otherInst];
  let otherCount = 0;

  for (let i = headerIdx + 1; i < lines.length; i++) {
    const cols = parseCSVRow(lines[i]);
    if (cols.length < 12) continue;

    const rawStrike = strikeCol !== -1 && strikeCol < cols.length ? numVal(cols[strikeCol]) : 0;
    if (rawStrike >= otherRange.min && rawStrike <= otherRange.max && (rawStrike < sr.min || rawStrike > sr.max)) {
      otherCount++;
    }

    let strike = strikeCol !== -1 && strikeCol < cols.length ? numVal(cols[strikeCol]) : NaN;
    if (strikeCol === -1 || !strike) {
      strike = NaN;
      for (const col of cols) {
        const value = numVal(col);
        if (value >= sr.min && value <= sr.max && value % 50 === 0) {
          strike = value;
          break;
        }
      }
    }
    if (!strike || Number.isNaN(strike) || strike < sr.min || strike > sr.max) continue;

    const callOI = numVal(cols[1]);
    const callChg = numVal(cols[2]);
    const callLTP = numVal(cols[5]);
    const putOI = numVal(cols[21] ?? cols[cols.length - 2] ?? "");
    const putChg = numVal(cols[20] ?? cols[cols.length - 3] ?? "");
    const putLTP = numVal(cols[17] ?? cols[cols.length - 6] ?? "");

    rows.push({ strike, callOI, callChg, callLTP, putOI, putChg, putLTP });
    totalCallOI += callOI;
    totalPutOI += putOI;
  }

  if (!rows.length) {
    if (otherCount) {
      const names = { NIFTY: "Nifty 50", BANKNIFTY: "Bank Nifty" };
      alert(`These strikes look like ${names[otherInst]}, but ${names[instrument]} is selected. Switch the instrument and upload again.`);
    } else {
      alert("Could not read any strikes from this CSV. Please upload the full NSE option-chain CSV (all strikes for one expiry).");
    }
    return false;
  }

  rows.sort((a, b) => a.strike - b.strike);
  const maxCallRow = rows.reduce((max, row) => (row.callOI > max.callOI ? row : max), rows[0]);
  const maxPutRow = rows.reduce((max, row) => (row.putOI > max.putOI ? row : max), rows[0]);
  const liquid = rows.filter((row) => row.callLTP > 0 && row.putLTP > 0);
  const atmRow = liquid.length
    ? liquid.reduce((best, row) =>
        Math.abs(row.callLTP - row.putLTP) < Math.abs(best.callLTP - best.putLTP) ? row : best,
      liquid[0])
    : rows[Math.floor(rows.length / 2)];
  const pcr = totalCallOI > 0 ? totalPutOI / totalCallOI : 1;

  const data = { rows, totalCallOI, totalPutOI, pcr, maxCallRow, maxPutRow, atmRow };
  latestSnapshot = buildSnapshot(data);
  renderDashboard(data);
  return true;
}

/* ---------- Single-strike CSV (one strike across expiries) ---------- */

function guessStrikeFromName(fileName) {
  const base = String(fileName).replace(/\.csv$/i, "");
  for (const match of base.match(/\d[\d,]*(?:\.\d+)?/g) || []) {
    const value = numVal(match);
    if (value >= STRIKE_RANGE.NIFTY.min && value <= STRIKE_RANGE.BANKNIFTY.max) return value;
  }
  return 0;
}

function resolveStrike(fileName) {
  const typed = numVal(document.getElementById("strikeInput").value);
  let strike = typed || guessStrikeFromName(fileName);
  if (!strike) {
    strike = numVal(window.prompt("Enter the strike price of this CSV (e.g. 23050):") || "");
  }
  if (!strike) {
    document.getElementById("strikeInput").focus();
    alert("Strike price is needed for a single-strike CSV. Type it in the Strike Price box and upload again.");
    return 0;
  }
  const sr = STRIKE_RANGE[instrument];
  if (strike < sr.min || strike > sr.max) {
    const names = { NIFTY: "Nifty 50", BANKNIFTY: "Bank Nifty" };
    const other = instrument === "NIFTY" ? "BANKNIFTY" : "NIFTY";
    const otherRange = STRIKE_RANGE[other];
    alert(
      strike >= otherRange.min && strike <= otherRange.max
        ? `Strike ${strike.toLocaleString()} looks like ${names[other]}, but ${names[instrument]} is selected. Switch the instrument and upload again.`
        : `Strike ${strike.toLocaleString()} is outside the ${names[instrument]} range. Check the Strike Price box.`,
    );
    return 0;
  }
  return strike;
}

function parseStrikeCSV(lines, fileName) {
  const headerIdx = lines.findIndex((line) => line.toUpperCase().includes("EXPIRY DATE"));
  const rows = [];
  for (let i = (headerIdx === -1 ? 1 : headerIdx) + 1; i < lines.length; i++) {
    const cols = parseCSVRow(lines[i]);
    if (cols.length < 22 || !/\d{1,2}-[A-Za-z]{3}-\d{4}/.test(cols[11])) continue;
    rows.push({
      expiry: cols[11],
      callOI: numVal(cols[1]),
      callChg: numVal(cols[2]),
      callVol: numVal(cols[3]),
      callIV: numVal(cols[4]),
      callLTP: numVal(cols[5]),
      putLTP: numVal(cols[17]),
      putIV: numVal(cols[18]),
      putVol: numVal(cols[19]),
      putChg: numVal(cols[20]),
      putOI: numVal(cols[21]),
    });
  }
  if (!rows.length) {
    alert("Could not read any expiries from this CSV. Please upload the NSE single-strike CSV (one strike, all expiries).");
    return false;
  }

  const strike = resolveStrike(fileName);
  if (!strike) return false;

  const data = computeStrikeData(strike, rows);
  latestSnapshot = buildStrikeSnapshot(data);
  renderDashboard(data);
  return true;
}

function expiryTime(text) {
  const time = new Date(String(text).replace(/-/g, " ")).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function computeStrikeData(strike, rawRows) {
  const rows = [...rawRows].sort((a, b) => expiryTime(a.expiry) - expiryTime(b.expiry));
  const sum = (key) => rows.reduce((total, row) => total + (Number(row[key]) || 0), 0);
  const totalCallOI = sum("callOI");
  const totalPutOI = sum("putOI");
  const nearest = rows.find((row) => row.callLTP > 0 && row.putLTP > 0) || rows[0];
  const hasPremium = nearest.callLTP > 0 && nearest.putLTP > 0;
  const straddle = hasPremium ? nearest.callLTP + nearest.putLTP : 0;
  return {
    mode: "strike",
    strike,
    rows,
    totalCallOI,
    totalPutOI,
    totalCallChg: sum("callChg"),
    totalPutChg: sum("putChg"),
    pcr: totalCallOI > 0 ? totalPutOI / totalCallOI : 1,
    nearest,
    nearestPcr: nearest.callOI > 0 ? nearest.putOI / nearest.callOI : 0,
    straddle,
    impliedSpot: hasPremium ? strike + nearest.callLTP - nearest.putLTP : 0,
    upperBE: straddle ? strike + straddle : 0,
    lowerBE: straddle ? strike - straddle : 0,
  };
}

function buildStrikeSnapshot(data) {
  const round = (n) => Number(Number(n).toFixed(2));
  return {
    instrument,
    mode: "strike",
    fileName: currentFileName,
    metrics: { pcr: round(data.pcr), totalCallOI: data.totalCallOI, totalPutOI: data.totalPutOI },
    levels: {
      strike: data.strike,
      nearestExpiry: data.nearest.expiry,
      straddle: round(data.straddle),
      impliedSpot: round(data.impliedSpot),
      upperBE: round(data.upperBE),
      lowerBE: round(data.lowerBE),
    },
    expiryRows: data.rows,
  };
}

function guessExpiryFromName(fileName) {
  const match = String(fileName).match(/(\d{1,2})-([A-Za-z]{3})-(\d{4})/);
  return match ? `${match[1].padStart(2, "0")} ${match[2]} ${match[3]}` : "";
}

function buildSnapshot(data) {
  const { rows, totalCallOI, totalPutOI, pcr, maxCallRow, maxPutRow, atmRow } = data;
  return {
    instrument,
    expiry: guessExpiryFromName(currentFileName),
    fileName: currentFileName,
    metrics: {
      pcr: Number(pcr.toFixed(2)),
      totalCallOI,
      totalPutOI,
    },
    levels: {
      atm: atmRow.strike,
      maxCallStrike: maxCallRow.strike,
      maxCallOI: maxCallRow.callOI,
      maxCallChg: maxCallRow.callChg,
      maxPutStrike: maxPutRow.strike,
      maxPutOI: maxPutRow.putOI,
      maxPutChg: maxPutRow.putChg,
    },
    chartRows: getChartRows(rows, atmRow).map(({ strike, callOI, callChg, putOI, putChg }) => ({
      strike,
      callOI,
      callChg,
      putOI,
      putChg,
    })),
    topStrikes: [...rows]
      .sort((a, b) => b.callOI + b.putOI - (a.callOI + a.putOI))
      .slice(0, 12)
      .map(({ strike, callOI, callChg, putOI, putChg }) => ({
        strike,
        callOI,
        callChg,
        putOI,
        putChg,
      })),
  };
}

function fmt(n) {
  const value = Number(n || 0);
  if (value >= 10000000) return `${(value / 10000000).toFixed(2)}Cr`;
  if (value >= 100000) return `${(value / 100000).toFixed(2)}L`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return value.toFixed(0);
}

function renderDashboard(data) {
  renderOiSections(data, instrument);
  showDashboard(true);
  saveSnapshot();
  if (aiEnabled) {
    generateAISignal();
  } else {
    showAiPrompt();
  }
}

function renderOiSections(data, inst) {
  const isStrike = data.mode === "strike";
  document.getElementById("expiryTablePanel").classList.toggle("hidden", !isStrike);
  document.getElementById("oiPanelTitle").textContent = isStrike
    ? `Open Interest By Expiry · Strike ${data.strike.toLocaleString()}`
    : "Open Interest By Strike";
  document.getElementById("levelsPanelTitle").textContent = isStrike ? "Breakevens & Spot" : "Key Levels";
  if (isStrike) {
    renderStrikeSections(data, inst);
    return;
  }

  const { rows, totalCallOI, totalPutOI, pcr, maxCallRow, maxPutRow, atmRow } = data;
  const { bias, biasClass } = getBias(pcr);

  const banner = document.getElementById("signalBanner");
  banner.className = `signal-banner ${biasClass}`;
  document.getElementById("sigWord").textContent = bias;
  document.getElementById("pcrBig").textContent = pcr.toFixed(2);
  document.getElementById("sigTag").textContent =
    `${inst === "BANKNIFTY" ? "Bank Nifty" : "Nifty 50"} Bias`;

  const pcrColor = biasClass === "bull" ? "bull" : biasClass === "bear" ? "bear" : "warn";
  document.getElementById("metricsGrid").innerHTML = [
    { label: "PCR", val: pcr.toFixed(2), cls: pcrColor },
    { label: "Total Call OI", val: fmt(totalCallOI), cls: "bear" },
    { label: "Total Put OI", val: fmt(totalPutOI), cls: "bull" },
    { label: "ATM Strike", val: atmRow.strike.toLocaleString(), cls: "blue" },
    { label: "Max Call Strike", val: maxCallRow.strike.toLocaleString(), cls: "bear" },
    { label: "Max Put Strike", val: maxPutRow.strike.toLocaleString(), cls: "bull" },
    { label: "Call OI at Max", val: fmt(maxCallRow.callOI), cls: "bear" },
    { label: "Put OI at Max", val: fmt(maxPutRow.putOI), cls: "bull" },
  ].map((m) => `
    <div class="metric">
      <div class="metric-label">${m.label}</div>
      <div class="metric-val ${m.cls}">${m.val}</div>
    </div>`).join("");

  renderOiChart(rows, atmRow, maxCallRow, maxPutRow);
  renderLevels(maxCallRow, maxPutRow, atmRow);
}

function showAiPrompt(errorMessage = "") {
  const loading = document.getElementById("aiLoading");
  loading.className = "ai-loading prompt";
  loading.style.display = "flex";
  loading.innerHTML = `
    ${errorMessage ? `<span class="warn">AI signal unavailable (${escHtml(errorMessage)}) - OI data above is still valid.</span>` : ""}
    <button class="ai-cta" id="aiRunBtn" type="button">
      <span class="ai-cta-inner"><span class="ai-spark">&#10022;</span>${errorMessage ? "Retry with AI" : "Analyse with AI"}</span>
    </button>
    ${errorMessage ? "" : '<span class="ai-hint">Adds an AI trade plan to this saved analysis.</span>'}`;
  document.getElementById("aiContent").classList.remove("show");
  document.getElementById("aiRunBtn").addEventListener("click", generateAISignal);
}

function showDashboard(withCsvPanels) {
  document.getElementById("uploadSection").classList.add("hidden");
  document.getElementById("dashboard").classList.remove("hidden");
  document.getElementById("uploadNewBtn").classList.remove("hidden");
  document.getElementById("metricsGrid").classList.toggle("hidden", !withCsvPanels);
  document.getElementById("csvPanels").classList.toggle("hidden", !withCsvPanels);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setSource(text) {
  const info = document.getElementById("sourceInfo");
  info.classList.toggle("hidden", !text);
  document.getElementById("sourceName").textContent = text || "--";
  document.getElementById("sourceName").title = text || "";
}

function directionClass(dir) {
  const d = String(dir || "").toUpperCase();
  if (d === "BUY CALL") return "bull";
  if (d === "BUY PUT") return "bear";
  return "warn";
}

function markActiveHistory() {
  document.querySelectorAll(".history-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === String(activeHistoryId));
  });
}

function getBias(pcr) {
  if (pcr > 1.5) return { bias: "Strongly Bullish", biasClass: "bull" };
  if (pcr > 1.2) return { bias: "Bullish", biasClass: "bull" };
  if (pcr > 0.9) return { bias: "Neutral", biasClass: "neut" };
  if (pcr > 0.7) return { bias: "Bearish", biasClass: "bear" };
  return { bias: "Strongly Bearish", biasClass: "bear" };
}

function getChartRows(rows, atmRow) {
  const atmIdx = rows.indexOf(atmRow);
  return rows.slice(Math.max(0, atmIdx - 5), Math.min(rows.length, atmIdx + 6));
}

function renderOiChart(rows, atmRow, maxCallRow, maxPutRow) {
  const visible = getChartRows(rows, atmRow);
  const maxOI = Math.max(...visible.map((row) => Math.max(row.callOI, row.putOI))) || 1;

  document.getElementById("oiChart").innerHTML = `
    <div class="oi-row header">
      <div>CALL OI</div><div></div><div>STRIKE</div><div></div><div>CHG</div><div>PUT OI</div>
    </div>
    ${visible.map((row) => {
      const callW = ((row.callOI / maxOI) * 100).toFixed(1);
      const putW = ((row.putOI / maxOI) * 100).toFixed(1);
      const isATM = row.strike === atmRow.strike;
      const isMaxC = row.strike === maxCallRow.strike;
      const isMaxP = row.strike === maxPutRow.strike;
      return `
        <div class="oi-row ${isATM ? "is-atm" : ""}">
          <div class="call-num">${fmt(row.callOI)}</div>
          <div class="bar-wrap-call"><div class="bar call" style="width:${callW}%"></div></div>
          <div class="strike-label ${isATM ? "atm-tag" : ""}">
            ${row.strike.toLocaleString()}${isATM ? '<em class="tag atm">ATM</em>' : ""}${isMaxC ? '<em class="tag res">R</em>' : ""}${isMaxP ? '<em class="tag sup">S</em>' : ""}
          </div>
          <div class="bar-wrap-put"><div class="bar put" style="width:${putW}%"></div></div>
          <div class="chg ${row.putChg > 0 ? "pos" : ""}">${row.putChg > 0 ? "+" : ""}${fmt(row.putChg)}</div>
          <div class="put-num">${fmt(row.putOI)}</div>
        </div>`;
    }).join("")}`;
}

function renderLevels(maxCallRow, maxPutRow, atmRow) {
  document.getElementById("levelList").innerHTML = [
    { name: "Strong Resistance", val: maxCallRow.strike.toLocaleString(), cls: "bear" },
    { name: "Resistance Zone", val: (maxCallRow.strike + 200).toLocaleString(), cls: "bear" },
    { name: "ATM Area", val: atmRow.strike.toLocaleString(), cls: "blue" },
    { name: "Support Zone", val: (maxPutRow.strike - 200).toLocaleString(), cls: "bull" },
    { name: "Strong Support", val: maxPutRow.strike.toLocaleString(), cls: "bull" },
  ].map((level) => `
    <div class="level-item">
      <div class="level-name">${level.name}</div>
      <div class="level-val ${level.cls}">${level.val}</div>
    </div>`).join("");
}

function setSaveBadge(state) {
  const badge = document.getElementById("saveBadge");
  const labels = {
    saving: "Saving...",
    saved: "Saved",
    ai: "Saved + AI plan",
    failed: "Not saved",
  };
  badge.classList.toggle("hidden", !state);
  badge.textContent = labels[state] || "";
  badge.className = `save-badge ${state || "hidden"}`;
}

function saveSnapshot() {
  const snap = latestSnapshot;
  currentAnalysisId = "";
  setSaveBadge("saving");
  savePromise = (async () => {
    try {
      const res = await fetch(apiUrl("/api/analyses"), {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ snapshot: snap }),
      });
      const data = await readApiJson(res);
      if (!res.ok || !data.id) throw new Error(data.error || "Not saved.");
      if (latestSnapshot === snap) {
        currentAnalysisId = data.id;
        activeHistoryId = data.id;
        setSaveBadge("saved");
      }
      await loadHistory();
    } catch (error) {
      if (latestSnapshot === snap) setSaveBadge("failed");
    }
  })();
  return savePromise;
}

function snapshotFromSaved(item) {
  return {
    instrument: item.instrument,
    expiry: item.expiry || undefined,
    fileName: item.file_name || undefined,
    mode: item.mode === "strike" ? "strike" : undefined,
    metrics: item.metrics,
    levels: item.levels,
    topStrikes: item.top_strikes,
    chartRows: item.chart_rows,
    expiryRows: item.expiry_rows,
  };
}

async function generateAISignal() {
  if (!latestSnapshot) return;
  setAiLoading("Generating AI analysis...");

  try {
    await savePromise;
    const res = await fetch(apiUrl("/api/analyze"), {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ snapshot: latestSnapshot, analysis_id: currentAnalysisId || undefined }),
    });
    const data = await readApiJson(res);
    if (!res.ok) throw new Error(data.error || "AI analysis failed.");

    renderTradeplan(data.analysis);
    if (data.id) {
      currentAnalysisId = data.id;
      activeHistoryId = data.id;
      setSaveBadge("ai");
    }
    await loadHistory();
  } catch (error) {
    showAiError(error.message || "AI analysis failed.");
  }
}

function setAiLoading(message) {
  const loading = document.getElementById("aiLoading");
  loading.className = "ai-loading";
  loading.style.display = "flex";
  loading.innerHTML = `<div class="spin"></div>${escHtml(message)}`;
  document.getElementById("aiContent").classList.remove("show");
}

function showAiError(message) {
  if (latestSnapshot) {
    showAiPrompt(message);
    return;
  }
  document.getElementById("aiLoading").className = "ai-loading";
  document.getElementById("aiLoading").style.display = "flex";
  document.getElementById("aiLoading").innerHTML =
    `<span class="warn">AI signal unavailable (${escHtml(message)}) - OI data above is still valid.</span>`;
}

function renderTradeplan(r) {
  const dir = String(r.primary_direction || "WAIT").toUpperCase();
  const isBull = dir === "BUY CALL";
  const isBear = dir === "BUY PUT";
  const cardClass = isBull ? "call-trade" : isBear ? "put-trade" : "wait-trade";
  const entColor = isBull ? "bull" : isBear ? "bear" : "warn";

  document.getElementById("primaryTrade").innerHTML = `
    <div class="primary-trade ${cardClass}">
      <div class="pt-left">
        <div class="pt-action">Primary Signal</div>
        <div class="pt-type ${entColor}">${escHtml(dir)}</div>
        <div class="pt-sub">
          ${isBull ? `Buy <strong>${escHtml(r.suggested_strike)} CE</strong>` : isBear ? `Buy <strong>${escHtml(r.suggested_strike)} PE</strong>` : "No clear edge - stand aside"}
          &nbsp; R:R <strong>${escHtml(r.risk_reward || "-")}</strong>
        </div>
      </div>
      <div class="pt-right">
        ${statBox("Entry", r.entry_zone, entColor)}
        ${statBox("Stop", formatMaybeNumber(r.stop_loss), "bear")}
        ${statBox("Target 1", formatMaybeNumber(r.target_1), "bull")}
        ${statBox("Target 2", formatMaybeNumber(r.target_2), "bull")}
      </div>
    </div>`;

  document.getElementById("tradeTableWrap").innerHTML = `
    <table class="trade-table">
      <thead><tr><th>Parameter</th><th>Value</th><th>Rule</th></tr></thead>
      <tbody>
        ${ruleRow("Entry Trigger", r.entry_zone, r.entry_trigger, entColor)}
        ${ruleRow("Stop Loss", formatMaybeNumber(r.stop_loss), "Hard invalidation level.", "bear")}
        ${ruleRow("Target 1", formatMaybeNumber(r.target_1), "Book partial profit.", "bull")}
        ${ruleRow("Target 2", formatMaybeNumber(r.target_2), "Final target.", "bull")}
        ${ruleRow("Early Exit", "Time / Price", r.exit_rule, "warn")}
      </tbody>
    </table>`;

  document.getElementById("tradeScenarios").innerHTML = `
    <div class="scenario">
      <div class="scenario-tag">Bull Scenario</div>
      <div class="scenario-text">${escHtml(r.bull_scenario)}</div>
    </div>
    <div class="scenario">
      <div class="scenario-tag">Bear Scenario</div>
      <div class="scenario-text">${escHtml(r.bear_scenario)}</div>
    </div>`;

  document.getElementById("aiAnalysis").textContent = r.oi_analysis || "";
  document.getElementById("whyBox").innerHTML = `
    <div class="why-box-title">Why This Trade</div>
    ${escHtml(r.reasoning)}`;
  document.getElementById("riskBox").innerHTML = `Risk to avoid: ${escHtml(r.risk_warning)}`;

  document.getElementById("aiLoading").style.display = "none";
  document.getElementById("aiContent").classList.add("show");
}

function statBox(label, value, cls) {
  return `
    <div class="pt-stat">
      <div class="pt-stat-label">${escHtml(label)}</div>
      <div class="pt-stat-val ${cls}">${escHtml(value || "-")}</div>
    </div>`;
}

function ruleRow(label, value, rule, cls) {
  return `
    <tr>
      <td class="label-col">${escHtml(label)}</td>
      <td class="val-col ${cls}">${escHtml(value || "-")}</td>
      <td class="reason-col">${escHtml(rule || "-")}</td>
    </tr>`;
}

function formatMaybeNumber(value) {
  return Number.isFinite(Number(value)) && Number(value) !== 0
    ? Number(value).toLocaleString()
    : value || "-";
}

async function loadHistory() {
  if (!authToken) return;
  const list = document.getElementById("historyList");
  list.innerHTML = '<div class="empty-state">Loading history...</div>';

  try {
    const res = await fetch(apiUrl("/api/analyses?limit=30"), {
      headers: authHeaders(),
    });
    const data = await readApiJson(res);
    if (!res.ok) throw new Error(data.error || "Could not load history.");
    renderHistory(data.items || []);
  } catch (error) {
    list.innerHTML = `<div class="empty-state">${escHtml(error.message || "Could not load history.")}</div>`;
  }
}

function csvTypeLabel(item) {
  if (item.mode === "strike") {
    const strike = item.strike ? Number(item.strike).toLocaleString() : "";
    return { kind: "strike", head: "STRIKE", detail: strike || "single strike", sub: "all expiries" };
  }
  return { kind: "expiry", head: "EXPIRY", detail: item.expiry || "full chain", sub: item.expiry ? "all strikes" : "all strikes" };
}

function hasAnalysis(item) {
  return item.has_analysis ?? Object.keys(item.analysis || {}).length > 0;
}

function renderHistory(items) {
  const list = document.getElementById("historyList");
  if (!items.length) {
    list.innerHTML = '<div class="empty-state">No saved analysis yet.</div>';
    return;
  }

  list.innerHTML = items.map((item) => `
    <button class="history-item ${hasAnalysis(item) ? directionClass(item.primary_direction) : "none"}-item" type="button" data-id="${escAttr(item.id)}">
      <div class="history-meta">
        <span class="inst-chip">${escHtml(item.instrument || "-")}</span>
        <span>${formatTime(item.created_at)}</span>
      </div>
      ${(() => {
        const t = csvTypeLabel(item);
        return `<div class="type-row"><span class="type-tag ${t.kind}"><b>${t.head}</b> ${escHtml(t.detail)}</span><span class="type-sub">${t.sub}</span></div>`;
      })()}
      <div class="history-signal ${hasAnalysis(item) ? directionClass(item.primary_direction) : "muted"}">${hasAnalysis(item) ? escHtml(item.primary_direction || "WAIT") : "No AI plan yet"}</div>
      <div class="history-meta">
        <span>${hasAnalysis(item) ? `AI pick ${escHtml(item.suggested_strike || "-")}` : "Not analysed"}</span>
        <span>PCR ${escHtml(item.metrics?.pcr ?? "-")}</span>
      </div>
    </button>`).join("");

  list.querySelectorAll(".history-item").forEach((button) => {
    button.addEventListener("click", () => loadHistoryDetail(button.dataset.id));
  });
  markActiveHistory();
}

async function loadHistoryDetail(id) {
  try {
    const res = await fetch(apiUrl(`/api/analyses/${id}`), { headers: authHeaders() });
    const data = await readApiJson(res);
    if (!res.ok) throw new Error(data.error || "Could not load analysis.");
    activeHistoryId = id;
    markActiveHistory();
    renderSavedAnalysis(data);
  } catch (error) {
    showAiError(error.message || "Could not load analysis.");
  }
}

function buildSavedData(item) {
  if (item.mode === "strike") {
    const strike = Number(item.levels?.strike);
    return strike && item.expiry_rows?.length ? computeStrikeData(strike, item.expiry_rows) : null;
  }
  const levels = item.levels || {};
  const metrics = item.metrics || {};
  const source = item.chart_rows?.length ? item.chart_rows : item.top_strikes;
  if (!levels.atm || !source?.length) return null;

  const rows = source
    .map((row) => ({
      strike: Number(row.strike),
      callOI: Number(row.callOI) || 0,
      callChg: Number(row.callChg) || 0,
      putOI: Number(row.putOI) || 0,
      putChg: Number(row.putChg) || 0,
    }))
    .sort((a, b) => a.strike - b.strike);

  let atmRow = rows.find((row) => row.strike === levels.atm);
  if (!atmRow) {
    atmRow = { strike: levels.atm, callOI: 0, callChg: 0, putOI: 0, putChg: 0 };
    rows.push(atmRow);
    rows.sort((a, b) => a.strike - b.strike);
  }

  const totalCallOI = Number(metrics.totalCallOI) || 0;
  const totalPutOI = Number(metrics.totalPutOI) || 0;
  const pcr = Number(metrics.pcr) || (totalCallOI ? totalPutOI / totalCallOI : 1);
  return {
    rows,
    totalCallOI,
    totalPutOI,
    pcr,
    atmRow,
    maxCallRow: { strike: levels.maxCallStrike, callOI: levels.maxCallOI || 0, callChg: levels.maxCallChg || 0 },
    maxPutRow: { strike: levels.maxPutStrike, putOI: levels.maxPutOI || 0, putChg: levels.maxPutChg || 0 },
  };
}

function renderSavedAnalysis(item) {
  const data = buildSavedData(item);
  const kind = csvTypeLabel(item);
  setSource(`Saved · ${item.instrument || "-"} · ${kind.head[0]}${kind.head.slice(1).toLowerCase()} ${kind.detail} · ${formatTime(item.created_at)}`);

  if (data) {
    renderOiSections(data, item.instrument);
    showDashboard(true);
    if (data.mode !== "strike" && !item.chart_rows?.length) {
      document.getElementById("oiChart").insertAdjacentHTML(
        "beforeend",
        '<div class="chart-note">Older save: showing the highest-OI strikes only.</div>',
      );
    }
  } else {
    showDashboard(false);
    const dirCls = directionClass(item.analysis?.primary_direction);
    document.getElementById("sigTag").textContent = `${item.instrument || "Saved"} Analysis`;
    document.getElementById("sigWord").textContent = item.analysis?.primary_direction || "Saved";
    document.getElementById("pcrBig").textContent = item.metrics?.pcr ?? "--";
    document.getElementById("signalBanner").className =
      `signal-banner ${dirCls === "warn" ? "neut" : dirCls}`;
  }
  latestSnapshot = snapshotFromSaved(item);
  currentAnalysisId = item.id;
  savePromise = Promise.resolve();
  setSaveBadge(hasAnalysis(item) ? "ai" : "saved");
  if (hasAnalysis(item)) {
    renderTradeplan(item.analysis);
  } else {
    showAiPrompt();
  }
}

function reset() {
  currentAnalysisId = "";
  setSaveBadge(null);
  latestSnapshot = null;
  activeHistoryId = "";
  markActiveHistory();
  setSource("");
  document.getElementById("uploadNewBtn").classList.add("hidden");
  document.getElementById("uploadSection").classList.remove("hidden");
  document.getElementById("dashboard").classList.add("hidden");
  document.getElementById("fileInput").value = "";
  document.getElementById("aiLoading").className = "ai-loading";
  document.getElementById("aiLoading").style.display = "flex";
  document.getElementById("aiLoading").innerHTML = '<div class="spin"></div>Generating AI analysis...';
  document.getElementById("aiContent").classList.remove("show");
  ["primaryTrade", "tradeTableWrap", "tradeScenarios", "whyBox", "riskBox"].forEach((id) => {
    document.getElementById(id).innerHTML = "";
  });
  document.getElementById("aiAnalysis").textContent = "";
}

async function readApiJson(resp) {
  const text = await resp.text();
  if (!text.trim()) {
    throw new Error(`Empty response from backend (${resp.status}).`);
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Non-JSON response from backend (${resp.status}).`);
  }
}

function parseServerDate(value) {
  if (!value) return null;
  let text = String(value);
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(text)) text += "Z";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

function timeAgo(value) {
  const date = parseServerDate(value);
  if (!date) return "-";
  const mins = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatTime(value) {
  const date = parseServerDate(value);
  if (!date) return "-";
  return date.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

function formatShortDate(value) {
  const date = parseServerDate(value);
  if (!date) return "-";
  return date.toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
  });
}

function escHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escAttr(value) {
  return escHtml(value).replace(/`/g, "&#96;");
}

/* ---------- Live options intelligence ---------- */

function scheduleLiveRefresh() {
  if (liveTimer) {
    clearInterval(liveTimer);
    liveTimer = null;
  }
  if (!authToken || !liveAutoRefresh) return;
  liveTimer = setInterval(() => {
    if (currentView === "live" && !liveLoading) loadLiveOptions(false);
  }, LIVE_REFRESH_MS);
}

async function loadLiveOptions(forceRefresh = false) {
  if (liveLoading || !authToken) return;
  liveLoading = true;
  const body = document.getElementById("liveBody");
  const btn = document.getElementById("liveRefreshBtn");
  const sourceState = document.getElementById("liveSourceState");
  btn.disabled = true;
  sourceState.textContent = "Fetching";
  if (!liveLoaded) {
    body.innerHTML = '<div class="ai-loading"><div class="spin"></div>Building live NIFTY option chain from Kite...</div>';
  }

  try {
    const liveParams = new URLSearchParams();
    if (forceRefresh) liveParams.set("refresh", "1");
    liveParams.set("_", String(Date.now()));
    const res = await fetch(apiUrl(`/api/live-options/snapshot?${liveParams.toString()}`), {
      headers: authHeaders(),
      cache: "no-store",
    });
    const data = await readApiJson(res);
    if (!res.ok || data.success === false) {
      throw Object.assign(new Error(data.message || data.error || "Could not load live options."), { data });
    }
    liveLoaded = true;
    window.lastLiveOptionsData = data;
    sourceState.textContent = kiteStatusLabel(data.status);
    sourceState.className = kiteStatusClass(data.status);
    renderLiveOptions(data);
  } catch (error) {
    const status = error.data?.status;
    sourceState.textContent = kiteStatusLabel(status, error.data?.error);
    sourceState.className = kiteStatusClass(status, error.data?.error);
    renderLiveError(error.message || "Could not load live options.", status, error.data || {});
  } finally {
    liveLoading = false;
    btn.disabled = false;
  }
}

function kiteStatusLabel(status, errorCode = "") {
  if (errorCode === "KITE_AUTH_REQUIRED" || status?.loginRequired || status?.authState === "AUTH_REQUIRED") {
    return "Kite Authentication Required";
  }
  if (status?.authState === "KITE_CONNECTED" || status?.authenticated) {
    return "Kite Connected";
  }
  if (status?.authState === "KITE_RECONNECTING" || status?.websocket?.state === "reconnecting") {
    return "Kite Reconnecting";
  }
  if (errorCode === "KITE_MARKET_CLOSED" || status?.marketState === "CLOSED") {
    return "Market Closed";
  }
  if (status) return "Kite Disconnected";
  return "Kite Unavailable";
}

function kiteStatusClass(status, errorCode = "") {
  const label = kiteStatusLabel(status, errorCode).toLowerCase();
  if (label.includes("connected")) return "bull";
  if (label.includes("auth")) return "bear";
  return "warn";
}

function liveBiasClass(direction) {
  const d = String(direction || "").toUpperCase();
  if (d === "BULLISH") return "bull";
  if (d === "BEARISH") return "bear";
  return "neut";
}

function liveScoreClass(score) {
  const value = Number(score) || 0;
  if (value > 0.5) return "bull";
  if (value < -0.5) return "bear";
  return "warn";
}

function fmtPrice(value) {
  const num = Number(value);
  return Number.isFinite(num) && num !== 0
    ? num.toLocaleString("en-IN", { maximumFractionDigits: 2 })
    : "-";
}

function renderLiveError(message, status, payload = {}) {
  const websocket = status?.websocket;
  const normalizedMessage = String(message || payload.message || payload.error || "");
  const oldTokenRequiredMessage =
    normalizedMessage.includes("KITE_ACCESS_TOKEN") ||
    normalizedMessage.includes("access token") ||
    normalizedMessage.includes("authentication");
  const loginRequired =
    payload.loginRequired ||
    status?.loginRequired ||
    payload.error === "KITE_AUTH_REQUIRED" ||
    oldTokenRequiredMessage;
  const title = loginRequired
    ? "Kite Authentication Required"
    : payload.error === "KITE_MARKET_CLOSED"
      ? "Market Closed"
      : "Live Options Unavailable";
  const displayMessage = loginRequired
    ? "Kite authentication is required. Access token is created by Zerodha login, so KITE_ACCESS_TOKEN is not required in env."
    : message;
  document.getElementById("liveUpdated").classList.add("hidden");
  document.getElementById("liveBody").innerHTML = `
    <section class="panel live-error">
      <div class="panel-title">${escHtml(title)}</div>
      <div class="empty-state warn">${escHtml(displayMessage)}</div>
      <div class="live-error-grid">
        <div><span>Kite Status</span><strong>${escHtml(kiteStatusLabel(status, payload.error))}</strong></div>
        <div><span>WebSocket</span><strong>${websocket?.enabled ? (websocket.connected ? "Connected" : websocket.state || "Enabled") : "Off"}</strong></div>
        <div><span>Market</span><strong>${escHtml(status?.marketState || "-")}</strong></div>
        <div><span>Last Connection</span><strong>${status?.last_successful_connection_at ? formatTime(status.last_successful_connection_at) : "-"}</strong></div>
        <div><span>Last Snapshot</span><strong>${status?.last_snapshot_at ? formatTime(status.last_snapshot_at) : "-"}</strong></div>
        <div><span>Error Code</span><strong>${escHtml(payload.error || "-")}</strong></div>
      </div>
      ${loginRequired ? '<button class="primary-btn kite-login-btn" type="button" onclick="openKiteLogin()">Login with Zerodha</button>' : ""}
      ${websocket?.error ? `<div class="risk-box">WebSocket: ${escHtml(websocket.error)}</div>` : ""}
    </section>`;
}

function renderLiveOptions(data) {
  const analysis = data.analysis || {};
  const snapshot = data.snapshot || {};
  const status = data.status || {};
  const cls = liveBiasClass(analysis.direction);
  const confidence = Number(analysis.confidence) || 0;
  const live = analysis.live_bias || {};
  const trend = analysis.trend_bias || {};
  const day = analysis.day_trend || {};
  const levels = analysis.support_resistance || {};
  const quality = analysis.data_quality || {};
  const websocket = status.websocket || {};
  const kiteLabel = kiteStatusLabel(status);
  const kiteCls = kiteStatusClass(status);
  const changeWindows = analysis.change_windows || {};
  if (!["3m", "15m", "session"].includes(liveWindowKey) || !changeWindows[liveWindowKey]) liveWindowKey = "3m";
  const selectedWindow = changeWindows[liveWindowKey] || changeWindows["3m"] || {};
  const selectedRows = selectedWindow.rows?.length ? selectedWindow.rows : analysis.strikes || [];

  document.getElementById("liveUpdated").classList.remove("hidden");
  document.getElementById("liveUpdatedAt").textContent = formatTime(analysis.timestamp || snapshot.timestamp);

  document.getElementById("liveBody").innerHTML = `
    <div class="live-board">
      <section class="design-panel overall-panel ${cls}">
        <div class="design-panel-head">
          <h2>OVERALL MARKET DIRECTION</h2>
          <span class="design-pill ${cls}">${confidence}%</span>
        </div>
        <div class="overall-direction ${cls}">${escHtml(analysis.direction || "INSUFFICIENT DATA")}</div>
        <p>${escHtml((analysis.explanations || [])[0] || "Signals are still building from aligned snapshots.")}</p>
        ${renderLiveTopMetrics(analysis, levels, status, quality)}
      </section>

      ${renderTimeframeCards(changeWindows, live, trend, day)}

      <section class="design-panel five-strike-intel">
        <div class="design-panel-head">
          <div>
            <h2>FIVE-STRIKE INTELLIGENCE</h2>
            <p>ATM ${analysis.atm ? Number(analysis.atm).toLocaleString("en-IN") : "-"} · ${formatShortDate(analysis.timestamp || snapshot.timestamp)}</p>
          </div>
          <div class="window-cluster">
            ${renderLiveWindowSelector(changeWindows)}
          </div>
        </div>
        ${!selectedWindow.available ? `<div class="table-note warn">${escHtml(selectedWindow.reason || "Need more saved snapshots for this window.")}</div>` : ""}
        ${renderPressureSummary(selectedWindow, selectedRows)}
        ${renderLiveStrikeTable(selectedRows, selectedWindow)}
      </section>

      <section class="design-panel context-panel">
        <div class="design-panel-head">
          <h2>MARKET CONTEXT</h2>
          <span class="design-pill ${kiteCls}">${escHtml(kiteLabel)}</span>
        </div>
        ${renderObservationList(analysis.observations || analysis.explanations || [])}
        ${(analysis.conflicts || []).length ? `<div class="conflict-list">${analysis.conflicts.map((item) => `<span>${escHtml(item)}</span>`).join("")}</div>` : ""}
        <details class="context-details">
          <summary>Connection & data quality</summary>
          ${renderLiveStructure(analysis, snapshot, status, websocket, quality, kiteLabel, kiteCls)}
        </details>
      </section>
    </div>`;
}

function renderLiveTopMetrics(analysis = {}, levels = {}, status = {}, quality = {}) {
  const pcrNum = Number(analysis.pcr);
  const pcr = Number.isFinite(pcrNum) ? pcrNum.toFixed(2) : "-";
  const support = levels.support ? Number(levels.support).toLocaleString("en-IN") : "-";
  const resistance = levels.resistance ? Number(levels.resistance).toLocaleString("en-IN") : "-";
  const wsConnected = Boolean(status.websocket?.connected);
  const wsEnabled = Boolean(status.websocket?.enabled);
  const metricItems = [
    ["Spot", fmtPrice(analysis.spot), analysis.spot_change ? signedPrice(analysis.spot_change) : "Live NIFTY", changeClass(analysis.spot_change)],
    ["PCR", pcr, pcr === "-" ? "Unavailable" : pcrNum >= 1 ? "Put OI dominance" : "Call OI dominance", pcr === "-" ? "neut" : pcrNum >= 1 ? "bull" : "bear"],
    ["Support", support, "Highest Put OI zone", "bull"],
    ["Resistance", resistance, "Highest Call OI zone", "bear"],
    ["Bull Score", signedPrice(analysis.bullish_score), "Directional weight", "bull"],
    ["Bear Score", signedPrice(analysis.bearish_score), "Directional weight", "bear"],
    ["WebSocket", wsConnected ? "Connected" : wsEnabled ? "Reconnecting" : "REST only", quality.status || "Data quality", wsConnected ? "bull" : wsEnabled ? "neut" : "bear"],
    ["Last Snapshot", quality.last_successful_snapshot_at ? formatTime(quality.last_successful_snapshot_at) : "-", status.marketState || "Market state", quality.last_successful_snapshot_at ? "bull" : "neut"],
  ];
  return `
    <div class="live-top-metrics">
      ${metricItems.map(([label, value, sub, cls]) => `
        <div class="live-top-card ${cls}">
          <span>${escHtml(label)}</span>
          <strong>${escHtml(value ?? "-")}</strong>
          <small>${escHtml(sub || "")}</small>
        </div>`).join("")}
    </div>`;
}

function renderTimeframeCards(changeWindows = {}, live = {}, trend = {}, day = {}) {
  const items = [
    ["3m", "LIVE ANALYSIS", "LAST 3 MIN", live],
    ["15m", "TREND ANALYSIS", "LAST 15 MIN", trend],
    ["session", "DAY TRACK", "MARKET OPEN TO NOW", day],
  ];
  return `
    <section class="timeframe-card-grid">
      ${items.map(([key, title, subtitle, bias]) => renderTimeframeCard(key, title, subtitle, bias, changeWindows[key] || {})).join("")}
    </section>`;
}

function renderTimeframeCard(key, title, subtitle, bias = {}, windowData = {}) {
  const direction = bias.direction || windowData.direction || "INSUFFICIENT DATA";
  const cls = liveBiasClass(direction);
  const confidence = Number(bias.confidence || windowData.confidence || 0);
  const call = aggregateSideSignal(windowData, "call");
  const put = aggregateSideSignal(windowData, "put");
  return `
    <article class="timeframe-card ${cls} ${liveWindowKey === key ? "active" : ""}" role="button" tabindex="0" onclick="setLiveWindow('${key}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();setLiveWindow('${key}')}">
      <span class="tf-active-mark">${liveWindowKey === key ? "Selected" : "View strikes"}</span>
      <div class="tf-card-head">
        <div>
          <strong>${escHtml(title)}</strong>
          <em>${escHtml(subtitle)}</em>
        </div>
        <b>${confidence}%</b>
      </div>
      ${!windowData?.available ? `<div class="tf-warn">${escHtml(windowData?.reason || "Need more saved snapshots.")}</div>` : ""}
      <div class="tf-side-grid">
        ${renderTimeframeSide("CALL", call)}
        ${renderTimeframeSide("PUT", put)}
      </div>
      <div class="tf-combined ${cls}">
        <span>COMBINED</span>
        <strong>${escHtml(direction)}</strong>
        <p>${escHtml((bias.explanations || [])[0] || bias.what_changed || combinedWindowExplanation(call, put, direction))}</p>
      </div>
    </article>`;
}

function renderTimeframeSide(label, side) {
  const cls = liveBiasClass(side.bias);
  return `
    <div class="tf-side ${cls}">
      <span>${escHtml(label)}</span>
      <strong>${escHtml(side.position)}</strong>
      <div class="tf-move ${side.oiMove.cls}">
        <i>${side.oiMove.arrow}</i>
        <b>${pctFmt(side.oiPct)}</b>
        <small>OI ${signedFmt(side.oiChange)}</small>
      </div>
      <div class="tf-move ${side.premiumMove.cls}">
        <i>${side.premiumMove.arrow}</i>
        <b>${pctFmt(side.premiumPct)}</b>
        <small>Premium ${signedPrice(side.premiumChange)}</small>
      </div>
    </div>`;
}

function renderBiasCard(title, bias, windowData = {}) {
  const cls = liveBiasClass(bias?.direction);
  const change = bias?.change || windowData?.change || {};
  return `
    <section class="panel bias-card ${cls}">
      <div class="bias-card-head">
        <div>
          <div class="section-label">${escHtml(title)}</div>
          <strong class="${cls}">${escHtml(bias?.direction || "INSUFFICIENT DATA")}</strong>
        </div>
        <span>${Number(bias?.confidence || 0)}%</span>
      </div>
      ${renderBiasChangeGrid(change, windowData)}
    </section>`;
}

function renderBiasChangeGrid(change = {}, windowData = {}) {
  if (!windowData?.available && !Object.keys(change || {}).length) {
    return `<div class="window-empty">${escHtml(windowData?.reason || "Need more saved snapshots.")}</div>`;
  }
  const items = [
    ["Spot", change.spot_change, change.spot_change_pct, "pts"],
    ["Call OI", change.call_oi_change, change.call_oi_change_pct, ""],
    ["Put OI", change.put_oi_change, change.put_oi_change_pct, ""],
    ["Call Prem", change.call_premium_change, change.call_premium_change_pct, ""],
    ["Put Prem", change.put_premium_change, change.put_premium_change_pct, ""],
  ];
  return `
    <div class="bias-change-grid">
      ${items.map(([label, value, pct, unit]) => `
        <div class="${changeClass(value)}">
          <span>${escHtml(label)}</span>
          <strong>${pctFmt(pct)}</strong>
          <small>${signedFmt(value)}${unit ? ` ${unit}` : ""}</small>
        </div>`).join("")}
    </div>`;
}

function renderAnalysisPanel(title, bias = {}, windowData = {}) {
  const cls = liveBiasClass(bias.direction || windowData.direction);
  const call = aggregateSideSignal(windowData, "call");
  const put = aggregateSideSignal(windowData, "put");
  return `
    <section class="design-panel live-analysis-card ${cls}">
      <div class="design-panel-head">
        <h2>${escHtml(title)}</h2>
        <span class="design-pill ${cls}">${Number(bias.confidence || windowData.confidence || 0)}%</span>
      </div>
      ${!windowData?.available ? `<div class="table-note warn">${escHtml(windowData?.reason || "Need more saved snapshots.")}</div>` : ""}
      <div class="analysis-two-col">
        ${renderAnalysisBox("CALL ANALYSIS", call)}
        ${renderAnalysisBox("PUT ANALYSIS", put)}
      </div>
      <div class="combined-direction ${cls}">
        <span>COMBINED DIRECTION</span>
        <strong>${escHtml(bias.direction || windowData.direction || "INSUFFICIENT DATA")}</strong>
        <p>${escHtml((bias.explanations || [])[0] || bias.what_changed || combinedWindowExplanation(call, put, bias.direction || windowData.direction))}</p>
      </div>
    </section>`;
}

function renderAnalysisBox(title, side) {
  const cls = liveBiasClass(side.bias);
  return `
    <div class="analysis-box">
      <h3>${escHtml(title)}</h3>
      <span class="design-pill ${cls}">${escHtml(side.bias)}</span>
      <div class="analysis-sep"></div>
      <div class="analysis-label">OI CHANGE</div>
      <div class="analysis-value ${side.oiMove.cls}">${side.oiMove.arrow} ${pctFmt(side.oiPct)}</div>
      <div class="analysis-label">Premium Change</div>
      <div class="analysis-value ${side.premiumMove.cls}">${side.premiumMove.arrow} ${pctFmt(side.premiumPct)}</div>
      <div class="analysis-position ${cls}">${escHtml(side.position)}</div>
    </div>`;
}

function aggregateSideSignal(windowData = {}, sideKey = "call") {
  const change = windowData.change || {};
  const oiChange = change[`${sideKey}_oi_change`];
  const premiumChange = change[`${sideKey}_premium_change`];
  const oiPct = change[`${sideKey}_oi_change_pct`];
  const premiumPct = change[`${sideKey}_premium_change_pct`];
  const classified = classifySideMovement(sideKey, oiChange, premiumChange);
  return {
    ...classified,
    oiChange,
    premiumChange,
    oiPct,
    premiumPct,
    oiMove: movementDirection(oiChange),
    premiumMove: movementDirection(premiumChange),
  };
}

function classifySideMovement(sideKey, oiChange, premiumChange) {
  const oiSign = Number(oiChange) > 0 ? 1 : Number(oiChange) < 0 ? -1 : 0;
  const premiumSign = Number(premiumChange) > 0 ? 1 : Number(premiumChange) < 0 ? -1 : 0;
  if (!oiSign || !premiumSign) {
    return { position: "Insufficient Data", pressure: "PENDING", bias: "NEUTRAL" };
  }
  const position =
    oiSign > 0 && premiumSign > 0 ? "Long Build-up" :
    oiSign > 0 && premiumSign < 0 ? "Short Build-up" :
    oiSign < 0 && premiumSign > 0 ? "Short Covering" :
    "Long Unwinding";
  const callMap = {
    "Long Build-up": "BULLISH",
    "Short Build-up": "BEARISH",
    "Short Covering": "BULLISH",
    "Long Unwinding": "BEARISH",
  };
  const putMap = {
    "Long Build-up": "BEARISH",
    "Short Build-up": "BULLISH",
    "Short Covering": "BEARISH",
    "Long Unwinding": "BULLISH",
  };
  const pressure =
    position === "Long Build-up" ? "BUYING" :
    position === "Short Build-up" ? "WRITING" :
    position === "Short Covering" ? "COVERING" :
    "UNWINDING";
  return {
    position,
    pressure,
    bias: sideKey === "call" ? callMap[position] : putMap[position],
  };
}

function combinedWindowExplanation(call, put, direction) {
  const finalBias = String(direction || "").toUpperCase();
  if (finalBias === "BULLISH" && call.bias === "BULLISH" && put.bias === "BULLISH") {
    return "Both Call and Put positioning indicate bullish pressure.";
  }
  if (finalBias === "BEARISH" && call.bias === "BEARISH" && put.bias === "BEARISH") {
    return "Both Call and Put positioning indicate bearish pressure.";
  }
  if (finalBias === "BULLISH") return "Bullish pressure is stronger across the selected window.";
  if (finalBias === "BEARISH") return "Bearish pressure is stronger across the selected window.";
  return "Call and Put signals are mixed or still building.";
}

function renderPressureSummary(windowData = {}, rows = []) {
  const call = aggregateSideSignal(windowData, "call");
  const put = aggregateSideSignal(windowData, "put");
  return `
    <div class="pressure-summary">
      ${renderPressureBlock("CALL PRESSURE", call)}
      ${renderPressureBlock("PUT PRESSURE", put)}
    </div>`;
}

function renderPressureBlock(label, side) {
  const cls = liveBiasClass(side.bias);
  return `
    <div class="pressure-block ${cls}">
      <span>${escHtml(label)}</span>
      <strong>${escHtml(side.pressure)} <i>${side.premiumMove.arrow}</i></strong>
      <p>OI ${signedFmt(side.oiChange)}</p>
      <p>Premium ${pctFmt(side.premiumPct)}</p>
    </div>`;
}

function renderObservationList(items) {
  const shown = (items || []).filter(Boolean).slice(0, 5);
  if (!shown.length) return '<div class="empty-state">No important observation available yet.</div>';
  return `<div class="observation-list">${shown.map((item) => `<div>${escHtml(item)}</div>`).join("")}</div>`;
}

function kiteDataQualityClass(quality = {}) {
  const status = String(quality.status || "").toLowerCase();
  if (status === "fresh") return "bull";
  if (status === "stale") return "warn";
  return "bear";
}

function signedPrice(value) {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return `${num > 0 ? "+" : ""}${num.toFixed(2)}`;
}

function liveMetric(label, value, sub, cls) {
  return `
    <div class="metric">
      <div class="metric-label">${escHtml(label)}</div>
      <div class="metric-val ${cls}">${escHtml(value ?? "-")}</div>
      <div class="metric-sub">${escHtml(sub || "")}</div>
    </div>`;
}

function renderLiveStrength(analysis) {
  const bull = Number(analysis.bullish_score) || 0;
  const bear = Number(analysis.bearish_score) || 0;
  const max = Math.max(bull, bear, 1);
  return `
    <div class="strength-list">
      <div class="strength-row">
        <div><strong class="bull">${bull.toFixed(2)}</strong><span>Bullish pressure</span></div>
        <i class="bull-fill" style="width:${Math.max(4, (bull / max) * 100)}%"></i>
      </div>
      <div class="strength-row">
        <div><strong class="bear">${bear.toFixed(2)}</strong><span>Bearish pressure</span></div>
        <i class="bear-fill" style="width:${Math.max(4, (bear / max) * 100)}%"></i>
      </div>
    </div>`;
}

function renderLiveStructure(analysis, snapshot, status, websocket, quality, kiteLabel, kiteCls) {
  const ivText = analysis.atm_iv ? `${analysis.atm_iv}%` : "Unavailable";
  const ivPct = analysis.iv_percentile ? `${analysis.iv_percentile}%` : "Unavailable";
  const wsText = websocket.connected ? "Connected" : (websocket.enabled ? (websocket.state || "Disconnected") : "REST only");
  const wsCls = websocket.connected ? "bull" : websocket.enabled ? "bear" : "warn";
  return `
    <div class="level-list live-structure">
      ${liveLevel("Kite Authentication", kiteLabel || kiteStatusLabel(status), kiteCls || kiteStatusClass(status))}
      ${liveLevel("WebSocket", wsText, wsCls)}
      ${liveLevel("Market", status.marketState || "Unknown", status.marketState === "OPEN" ? "bull" : "warn")}
      ${liveLevel("Last Tick", quality.last_tick_received_at ? formatTime(quality.last_tick_received_at) : "Unavailable", quality.last_tick_received_at ? "bull" : "warn")}
      ${liveLevel("Last Snapshot", quality.last_successful_snapshot_at ? formatTime(quality.last_successful_snapshot_at) : "Unavailable", quality.last_successful_snapshot_at ? "bull" : "warn")}
      ${liveLevel("Data Freshness", quality.status || "Unknown", kiteDataQualityClass(quality))}
      ${liveLevel("ATM Strike", analysis.atm ? Number(analysis.atm).toLocaleString("en-IN") : "-", "blue")}
      ${liveLevel("VWAP", analysis.vwap ? fmtPrice(analysis.vwap) : "Unavailable", analysis.vwap ? "blue" : "warn")}
      ${liveLevel("ATM IV", ivText, "warn")}
      ${liveLevel("IV Percentile", ivPct, "warn")}
    </div>
    <div class="chart-note">${escHtml(analysis.iv_note || snapshot.iv_note || "VWAP/IV are shown only when Kite or a model supplies them.")}</div>
    ${websocket?.error ? `<div class="risk-box">WebSocket: ${escHtml(websocket.error)}</div>` : ""}`;
}

function liveLevel(name, value, cls) {
  return `
    <div class="level-item">
      <div class="level-name">${escHtml(name)}</div>
      <div class="level-val ${cls || ""}">${escHtml(value)}</div>
    </div>`;
}

function renderLiveWindowSelector(windows = {}) {
  const options = [
    ["3m", "3 Min"],
    ["15m", "15 Min"],
    ["session", "Session"],
  ];
  return `
    <div class="window-selector">
      ${options.map(([key, label]) => {
        const item = windows[key] || {};
        return `<button class="window-btn ${liveWindowKey === key ? "active" : ""} ${item.available ? "" : "unavailable"}" type="button" onclick="setLiveWindow('${key}')">${label}</button>`;
      }).join("")}
    </div>`;
}

function renderWindowSummary(windowData = {}) {
  if (!windowData.available) {
    return `<div class="empty-state warn compact-window-empty">${escHtml(windowData.reason || "Need more saved snapshots for this window.")}</div>`;
  }
  const c = windowData.change || {};
  const items = [
    ["Spot", c.spot_change, c.spot_change_pct, "pts"],
    ["Call OI", c.call_oi_change, c.call_oi_change_pct, ""],
    ["Put OI", c.put_oi_change, c.put_oi_change_pct, ""],
    ["Call Prem", c.call_premium_change, c.call_premium_change_pct, ""],
    ["Put Prem", c.put_premium_change, c.put_premium_change_pct, ""],
    ["Overall", windowData.direction || "INSUFFICIENT DATA", windowData.confidence ?? 0, "summary"],
  ];
  return `
    <div class="window-summary-grid">
      ${items.map(([label, value, pct, unit]) => unit === "summary" ? `
        <div class="window-stat ${liveBiasClass(value)}">
          <span>${escHtml(label)}</span>
          <strong>${escHtml(value || "-")}</strong>
          <small>${Number(pct) || 0}% confidence</small>
        </div>` : `
        <div class="window-stat ${changeClass(value)}">
          <span>${escHtml(label)}</span>
          <strong>${pctFmt(pct)}</strong>
          <small>${signedFmt(value)}${unit ? ` ${unit}` : ""}</small>
        </div>`).join("")}
    </div>`;
}

function windowElapsed(windowData = {}) {
  if (!windowData.available) return windowData.reason || "waiting for saved snapshots";
  const mins = Number(windowData.elapsed_minutes);
  const label = Number.isFinite(mins) && mins > 0 ? `${mins.toFixed(mins >= 10 ? 0 : 1)} min change` : "latest change";
  const base = windowData.baseline_timestamp ? `from ${formatTime(windowData.baseline_timestamp)}` : "";
  return [label, base].filter(Boolean).join(" · ");
}

function renderPositioningNotes(live = {}, trend = {}, day = {}) {
  const notes = [
    ["Live Call Activity", live.call_activity || "Neutral"],
    ["Live Put Activity", live.put_activity || "Neutral"],
    ["Strongest Strike", live.strongest_contributor || "-"],
    ["15m Consistency", trend.trend_consistency || "-"],
    ["Session Control", day.buyers_vs_sellers || "Pending"],
    ["Session Intervals", day.interval_count ?? 0],
  ];
  return `<div class="bias-detail-list">${notes.map(([label, value]) => `
    <div><span>${escHtml(label)}</span><strong>${escHtml(value)}</strong></div>`).join("")}</div>`;
}

function renderLiveStrikeTable(rows, windowData = {}) {
  if (!rows.length) return '<div class="empty-state">No five-strike rows available.</div>';
  return `
    <div class="strike-card-list">
      ${rows.map((row) => renderStrikeCard(row, windowData)).join("")}
    </div>`;
}

function renderStrikeCard(row, windowData = {}) {
  const finalCls = liveBiasClass(row.net_interpretation);
  return `
    <article class="strike-intel-card ${row.is_atm ? "atm-card" : ""} ${finalCls}">
      <div class="strike-card-head">
        <div>
          <strong>${escHtml(row.label || "")} · ${Number(row.strike).toLocaleString("en-IN")}</strong>
          ${row.is_atm ? "<span>ATM focus strike</span>" : "<span>Nearby strike</span>"}
        </div>
        <div class="strike-final-pill ${finalCls}">${escHtml(row.net_interpretation || "NEUTRAL")}</div>
      </div>
      <div class="strike-mini-grid">
        ${renderStrikeMiniSide("CALL", row.call)}
        ${renderStrikeMiniSide("PUT", row.put)}
      </div>
      <div class="strike-signal-text ${finalCls}">
        <strong>${escHtml(signalHeadline(row.net_interpretation))}</strong>
        <p>${escHtml(strikeExplanation(row))}</p>
      </div>
      <details class="strike-expand">
        <summary>Directional calculation</summary>
        <div class="strike-detail-grid">
          ${renderSideDetails("Call", row.call)}
          ${renderSideDetails("Put", row.put)}
        </div>
      </details>
    </article>`;
}

function renderStrikeMiniSide(label, side = {}) {
  const cls = liveBiasClass(side.bias);
  const oiMove = movementDirection(side.interval_oi_change);
  const premiumMove = movementDirection(side.interval_premium_change);
  return `
    <section class="strike-mini-side ${cls}">
      <div class="strike-mini-head">
        <span>${escHtml(label)}</span>
        <b>${escHtml(side.bias || "NEUTRAL")}</b>
      </div>
      <strong>${escHtml(side.positioning || "Insufficient Data")}</strong>
      <div class="strike-mini-ltp">LTP ${fmtPrice(side.ltp)}</div>
      <div class="strike-mini-moves">
        <div class="${oiMove.cls}">
          <span>OI</span>
          <b>${oiMove.arrow} ${signedFmt(side.interval_oi_change)}</b>
          <small>${pctFmt(side.interval_oi_change_pct)}</small>
        </div>
        <div class="${premiumMove.cls}">
          <span>Premium</span>
          <b>${premiumMove.arrow} ${signedPrice(side.interval_premium_change)}</b>
          <small>${pctFmt(side.interval_premium_change_pct)}</small>
        </div>
      </div>
    </section>`;
}

function renderSideAnalysis(title, side = {}, sideKey = "") {
  const bias = liveBiasClass(side.bias);
  return `
    <section class="side-analysis ${sideKey} ${bias}">
      <div class="side-head">
        <strong>${escHtml(title)}</strong>
        <span class="position-badge ${bias}">${escHtml(side.bias || "NEUTRAL")}</span>
      </div>
      <div class="side-ltp">LTP <b>${fmtPrice(side.ltp)}</b></div>
      ${movementLine("OI", side.interval_oi_change, side.interval_oi_change_pct, side.bias)}
      ${movementLine("Premium", side.interval_premium_change, side.interval_premium_change_pct, side.bias, true)}
      <div class="position-row">
        <span>${escHtml(side.positioning || "Insufficient Data")}</span>
        <b class="${bias}">${escHtml(side.bias || "NEUTRAL")}</b>
      </div>
    </section>`;
}

function signalHeadline(direction) {
  const d = String(direction || "").toUpperCase();
  if (d === "BULLISH") return "Bullish pressure";
  if (d === "BEARISH") return "Bearish pressure";
  return "Mixed pressure";
}

function renderCompactMove(oiChange, premiumPct) {
  return `OI ${signedFmt(oiChange)} · Premium ${pctFmt(premiumPct)}`;
}

function renderCombinedSignal(row) {
  const cls = liveBiasClass(row.net_interpretation);
  return `
    <section class="combined-signal ${cls}">
      <span>COMBINED STRIKE SIGNAL</span>
      <strong>${escHtml(row.net_interpretation || "NEUTRAL")}</strong>
      <em>Score ${signedPrice(row.net_score)}</em>
      <p>${escHtml(strikeExplanation(row))}</p>
    </section>`;
}

function strikeExplanation(row) {
  const callBias = String(row.call?.bias || "NEUTRAL").toUpperCase();
  const putBias = String(row.put?.bias || "NEUTRAL").toUpperCase();
  const finalBias = String(row.net_interpretation || "NEUTRAL").toUpperCase();
  if (finalBias === "BULLISH" && callBias === "BULLISH" && putBias === "BULLISH") {
    return "Both call and put positioning support bullish pressure.";
  }
  if (finalBias === "BEARISH" && callBias === "BEARISH" && putBias === "BEARISH") {
    return "Both call and put positioning support bearish pressure.";
  }
  if (finalBias === "BULLISH") return "Bullish side has stronger weighted positioning at this strike.";
  if (finalBias === "BEARISH") return "Bearish side has stronger weighted positioning at this strike.";
  return "Call and put signals are mixed or too small for a clean edge.";
}

function movementLine(label, value, pct, bias, isPremium = false) {
  const move = movementDirection(value);
  const biasCls = liveBiasClass(bias);
  return `
    <div class="movement-line ${biasCls}">
      <div class="movement-top">
        <span>${escHtml(label)}</span>
        <strong><i class="${move.cls}">${move.arrow}</i> ${isPremium ? signedPrice(value) : signedFmt(value)} <small>${pctFmt(pct)}</small></strong>
      </div>
    </div>`;
}

function renderSideDetails(label, side = {}) {
  return `
    <div class="side-detail-box">
      <strong>${escHtml(label)}</strong>
      ${detailRow("Previous OI", fmtNullable(side.previous_oi))}
      ${detailRow("Current OI", fmtNullable(side.oi))}
      ${detailRow("OI Change", signedFmt(side.interval_oi_change))}
      ${detailRow("OI Change %", pctFmt(side.interval_oi_change_pct))}
      ${detailRow("Previous Premium", fmtPrice(side.previous_ltp))}
      ${detailRow("Current Premium", fmtPrice(side.ltp))}
      ${detailRow("Premium Change", signedPrice(side.interval_premium_change))}
      ${detailRow("Premium Change %", pctFmt(side.interval_premium_change_pct))}
      ${detailRow("Position", side.positioning || "-")}
      ${detailRow("Calculation", side.reason || "-")}
    </div>`;
}

function detailRow(label, value) {
  return `<div><span>${escHtml(label)}</span><b>${escHtml(value ?? "-")}</b></div>`;
}

function movementDirection(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num === 0) return { cls: "flat", arrow: "→" };
  return num > 0 ? { cls: "up", arrow: "↑" } : { cls: "down", arrow: "↓" };
}

function fmtNullable(value) {
  if (value === null || value === undefined || value === "") return "-";
  return fmt(value);
}

function renderChangeCell(value, pct) {
  const cls = changeClass(value);
  return `<div class="change-cell ${cls}"><strong>${signedFmt(value)}</strong><span>${pctFmt(pct)}</span></div>`;
}

function renderChangeText(value, pct) {
  const cls = changeClass(value);
  return `<span class="mini-change ${cls}">${signedPrice(value)} / ${pctFmt(pct)}</span>`;
}

function renderStrikeCalculations(row) {
  return `
    <div class="calc-grid">
      ${calcBox("Call OI", fmt(row.call?.oi), "Current")}
      ${calcBox("Call 3m OI", signedFmt(row.call?.interval_oi_change), pctFmt(row.call?.interval_oi_change_pct))}
      ${calcBox("Call 3m Premium", signedPrice(row.call?.interval_premium_change), pctFmt(row.call?.interval_premium_change_pct))}
      ${calcBox("Put OI", fmt(row.put?.oi), "Current")}
      ${calcBox("Put 3m OI", signedFmt(row.put?.interval_oi_change), pctFmt(row.put?.interval_oi_change_pct))}
      ${calcBox("Put 3m Premium", signedPrice(row.put?.interval_premium_change), pctFmt(row.put?.interval_premium_change_pct))}
    </div>`;
}

function calcBox(label, value, sub) {
  return `<span><em>${escHtml(label)}</em><strong>${escHtml(value ?? "-")}</strong><small>${escHtml(sub || "")}</small></span>`;
}

function pctFmt(value) {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return `${num > 0 ? "+" : ""}${num.toFixed(2)}%`;
}

function signedFmt(value) {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  const sign = num > 0 ? "+" : num < 0 ? "-" : "";
  return `${sign}${fmt(Math.abs(num))}`;
}

function changeClass(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num === 0) return "neut";
  return num > 0 ? "bull" : "bear";
}

/* ---------- News sentiment ---------- */

async function loadNews(forceRefresh = false) {
  if (newsLoading || !authToken) return;
  newsLoading = true;
  const body = document.getElementById("newsBody");
  const btn = document.getElementById("newsFetchBtn");
  const instName = newsInstrument === "BANKNIFTY" ? "Bank Nifty" : "Nifty 50";
  btn.disabled = true;
  body.innerHTML = `<div class="ai-loading"><div class="spin"></div>Fetching ${escHtml(instName)} news and scoring sentiment...</div>`;

  try {
    const query = `instrument=${newsInstrument}${forceRefresh ? "&refresh=1" : ""}`;
    const res = await fetch(apiUrl(`/api/news?${query}`), { headers: authHeaders() });
    const data = await readApiJson(res);
    if (!res.ok) {
      const failure = new Error(data.error || "Could not load news.");
      failure.details = data.details;
      throw failure;
    }
    newsLoaded[newsInstrument] = true;
    newsFilter = data.scope;
    renderNews(data);
  } catch (error) {
    const details = (error.details || []).map((line) => `<div>${escHtml(line)}</div>`).join("");
    body.innerHTML = `<div class="empty-state warn">${escHtml(error.message || "Could not load news.")}${details ? `<div class="error-details">${details}</div>` : ""}</div>`;
  } finally {
    newsLoading = false;
    btn.disabled = false;
  }
}

function renderNews(data) {
  const instName = data.instrument === "BANKNIFTY" ? "Bank Nifty" : "Nifty 50";
  const total = data.counts.bullish + data.counts.bearish + data.counts.neutral || 1;
  const pct = (n) => ((n / total) * 100).toFixed(0);

  document.getElementById("newsUpdated").classList.remove("hidden");
  document.getElementById("newsUpdatedAt").textContent = formatTime(data.fetched_at);

  const categories = data.categories.map((c) => {
    const cls = c.score >= 54 ? "bull" : c.score <= 46 ? "bear" : "warn";
    return `
      <div class="cat-row">
        <div class="cat-name">${escHtml(c.name)}<span>${c.count} headlines</span></div>
        <div class="cat-bar"><i class="${cls}-fill" style="width:${c.score}%"></i></div>
        <div class="cat-score ${cls}">${c.score}</div>
      </div>`;
  }).join("");

  lastNews = data;
  const topics = [data.scope, "All", ...data.categories.map((c) => c.name).filter((n) => n !== data.scope)];
  const filterChips = topics.map((name) => `
    <button class="filter-chip ${name === newsFilter ? "active" : ""}" type="button" data-filter="${escAttr(name)}">${escHtml(name)}</button>`).join("");
  const shown = data.items.filter((item) => newsFilter === "All" || item.category === newsFilter);

  const items = shown.map((item) => `
    <a class="news-item" href="${escAttr(item.link)}" target="_blank" rel="noopener noreferrer">
      <span class="news-pill ${escAttr(item.label)}">${escHtml(item.label)}</span>
      <div class="news-main">
        <div class="news-title">${escHtml(item.title)}</div>
        <div class="news-meta">
          <span>${escHtml(item.source)}</span>
          <span>${escHtml(item.category)}${item.inverse ? " (inverse)" : ""}</span>
          <span>${formatTime(item.published_at)} IST &middot; ${timeAgo(item.published_at)}</span>
        </div>
      </div>
    </a>`).join("");

  document.getElementById("newsBody").innerHTML = `
    <div class="news-summary">
      <section class="sentiment-card ${escAttr(data.bias_class)}">
        <div class="section-label">Overall Sentiment &middot; ${escHtml(instName)}</div>
        <div class="sent-score"><strong>${data.score}</strong><span>/ 100</span></div>
        <div class="sent-bias">${escHtml(data.bias)}</div>
        <div class="sent-meter"><i style="left:${Math.max(2, Math.min(98, data.score))}%"></i></div>
        <div class="sent-meter-labels"><span>Bearish</span><span>Neutral</span><span>Bullish</span></div>
        <div class="sent-counts">
          <div><strong class="bull">${data.counts.bullish}</strong><span>Bullish (${pct(data.counts.bullish)}%)</span></div>
          <div><strong class="warn">${data.counts.neutral}</strong><span>Neutral (${pct(data.counts.neutral)}%)</span></div>
          <div><strong class="bear">${data.counts.bearish}</strong><span>Bearish (${pct(data.counts.bearish)}%)</span></div>
        </div>
        <div class="drv-note">Based only on <strong>${escHtml(data.scope)}</strong> headlines (${data.counts.bullish + data.counts.bearish + data.counts.neutral}). The topics on the right are extra context and are not part of this score.</div>
      </section>
      <section class="panel">
        <div class="panel-title">Related Factors &middot; for context</div>
        <div class="cat-list">${categories || '<div class="empty-state">No topics.</div>'}</div>
        <div class="news-note">Scored from headline keywords, newer news counts more. Related topics are scored separately. Crude oil is inverse: a price rise is bearish for India. Indicative only, not financial advice.</div>
      </section>
    </div>
    <section class="panel">
      <div class="panel-title">Latest Headlines (${shown.length})</div>
      <div class="filter-row">${filterChips}</div>
      <div class="news-list">${items || '<div class="empty-state">No recent headlines found.</div>'}</div>
    </section>`;
}

function shortExpiry(text) {
  const [day, mon, year] = String(text).split("-");
  return year ? `${day} ${mon} ${year.slice(-2)}` : text;
}

function renderStrikeSections(data, inst) {
  const { bias, biasClass } = getBias(data.pcr);
  const name = inst === "BANKNIFTY" ? "Bank Nifty" : "Nifty 50";
  document.getElementById("signalBanner").className = `signal-banner ${biasClass}`;
  document.getElementById("sigWord").textContent = bias;
  document.getElementById("pcrBig").textContent = data.pcr.toFixed(2);
  document.getElementById("sigTag").textContent = `${name} · ${data.strike.toLocaleString()} Strike Bias`;

  const pcrColor = biasClass === "bull" ? "bull" : biasClass === "bear" ? "bear" : "warn";
  const money = (n) => (n > 0 ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "-");
  document.getElementById("metricsGrid").innerHTML = [
    { label: "PCR (All Expiries)", val: data.pcr.toFixed(2), cls: pcrColor },
    { label: "Total Call OI", val: fmt(data.totalCallOI), cls: "bear" },
    { label: "Total Put OI", val: fmt(data.totalPutOI), cls: "bull" },
    { label: "Nearest Expiry PCR", val: data.nearestPcr ? data.nearestPcr.toFixed(2) : "-", cls: "warn" },
    { label: "Implied Spot", val: data.impliedSpot ? Math.round(data.impliedSpot).toLocaleString() : "-", cls: "blue" },
    { label: "Straddle Premium", val: money(data.straddle), cls: "warn" },
    { label: "Call IV (Nearest)", val: data.nearest.callIV ? `${data.nearest.callIV}%` : "-", cls: "bear" },
    { label: "Put IV (Nearest)", val: data.nearest.putIV ? `${data.nearest.putIV}%` : "-", cls: "bull" },
  ].map((m) => `
    <div class="metric">
      <div class="metric-label">${m.label}</div>
      <div class="metric-val ${m.cls}">${m.val}</div>
    </div>`).join("");

  const maxOI = Math.max(...data.rows.map((row) => Math.max(row.callOI, row.putOI))) || 1;
  document.getElementById("oiChart").innerHTML = `
    <div class="oi-row header">
      <div>CALL OI</div><div></div><div>EXPIRY</div><div></div><div>CHG</div><div>PUT OI</div>
    </div>
    ${data.rows.map((row) => `
      <div class="oi-row ${row === data.nearest ? "is-atm" : ""}">
        <div class="call-num">${fmt(row.callOI)}</div>
        <div class="bar-wrap-call"><div class="bar call" style="width:${((row.callOI / maxOI) * 100).toFixed(1)}%"></div></div>
        <div class="strike-label">${escHtml(shortExpiry(row.expiry))}${row === data.nearest ? '<em class="tag atm">NEAR</em>' : ""}</div>
        <div class="bar-wrap-put"><div class="bar put" style="width:${((row.putOI / maxOI) * 100).toFixed(1)}%"></div></div>
        <div class="chg ${row.putChg > 0 ? "pos" : ""}">${row.putChg > 0 ? "+" : ""}${fmt(row.putChg)}</div>
        <div class="put-num">${fmt(row.putOI)}</div>
      </div>`).join("")}`;

  const levels = [];
  if (data.upperBE) levels.push({ name: "Upper Breakeven", val: Math.round(data.upperBE).toLocaleString(), cls: "bear" });
  if (data.impliedSpot) levels.push({ name: "Implied Spot", val: Math.round(data.impliedSpot).toLocaleString(), cls: "blue" });
  levels.push({ name: "Strike", val: data.strike.toLocaleString(), cls: "warn" });
  if (data.lowerBE) levels.push({ name: "Lower Breakeven", val: Math.round(data.lowerBE).toLocaleString(), cls: "bull" });
  levels.push({ name: "Nearest Expiry", val: shortExpiry(data.nearest.expiry), cls: "" });
  document.getElementById("levelList").innerHTML = levels.map((level) => `
    <div class="level-item">
      <div class="level-name">${level.name}</div>
      <div class="level-val ${level.cls}">${level.val}</div>
    </div>`).join("") +
    '<div class="chart-note">Implied spot and breakevens come from nearest-expiry option prices (LTP), so treat them as approximate.</div>';

  document.getElementById("expiryTableTitle").textContent = `Expiry-wise Data · Strike ${data.strike.toLocaleString()}`;
  const num = (v) => (v ? fmt(v) : "-");
  const price = (v) => (v ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "-");
  const chg = (v) => (v ? `${v > 0 ? "+" : ""}${fmt(v)}` : "-");
  document.getElementById("expiryTableWrap").innerHTML = `
    <table class="trade-table expiry-table">
      <thead><tr>
        <th>Expiry</th><th>Call OI</th><th>Chg OI</th><th>Volume</th><th>IV</th><th>LTP</th>
        <th>Put LTP</th><th>IV</th><th>Volume</th><th>Chg OI</th><th>Put OI</th><th>PCR</th>
      </tr></thead>
      <tbody>${data.rows.map((row) => {
        const rowPcr = row.callOI > 0 ? row.putOI / row.callOI : 0;
        return `
        <tr class="${row === data.nearest ? "near-row" : ""}">
          <td class="label-col">${escHtml(row.expiry)}</td>
          <td class="num bear">${num(row.callOI)}</td>
          <td class="num ${row.callChg > 0 ? "bear" : ""}">${chg(row.callChg)}</td>
          <td class="num">${num(row.callVol)}</td>
          <td class="num">${row.callIV || "-"}</td>
          <td class="num">${price(row.callLTP)}</td>
          <td class="num">${price(row.putLTP)}</td>
          <td class="num">${row.putIV || "-"}</td>
          <td class="num">${num(row.putVol)}</td>
          <td class="num ${row.putChg > 0 ? "bull" : ""}">${chg(row.putChg)}</td>
          <td class="num bull">${num(row.putOI)}</td>
          <td class="num ${rowPcr >= 1 ? "bull" : "bear"}">${rowPcr ? rowPcr.toFixed(2) : "-"}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

document.addEventListener("click", (event) => {
  const chip = event.target.closest?.(".filter-chip");
  if (!chip || !lastNews) return;
  newsFilter = chip.dataset.filter;
  renderNews(lastNews);
});
