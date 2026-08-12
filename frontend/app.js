const REFRESH_MS = 5000;

const state = {
  side: "ALL",
  deltaMin: 0.10,
  deltaMax: 0.35,
  minOi: 50000,
  minVolume: 0,
  expiry: "",
  lastUpdated: null,
  expandedRefId: null,
};

const el = (id) => document.getElementById(id);

function fmt(n, decimals = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("en-IN", { maximumFractionDigits: decimals, minimumFractionDigits: 0 });
}

function fmtSigned(n, decimals = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const s = fmt(Math.abs(n), decimals);
  return n > 0 ? `+${s}` : n < 0 ? `-${s}` : s;
}

function scoreBadge(score) {
  if (score === null || score === undefined) return `<span class="badge badge-none">—</span>`;
  let cls = "badge-critical", label = "Poor";
  if (score >= 75) { cls = "badge-good"; label = "Strong"; }
  else if (score >= 55) { cls = "badge-warning"; label = "Moderate"; }
  else if (score >= 35) { cls = "badge-serious"; label = "Weak"; }
  return `<span class="badge ${cls}">${fmt(score, 1)} · ${label}</span>`;
}

async function fetchScan() {
  const params = new URLSearchParams({
    side: state.side,
    delta_min: state.deltaMin,
    delta_max: state.deltaMax,
    min_oi: state.minOi,
    min_volume: state.minVolume,
  });
  if (state.expiry) params.set("expiry", state.expiry);

  try {
    const res = await fetch(`/api/scan?${params.toString()}`);
    const data = await res.json();
    if (!res.ok) {
      showError(data.message || "Failed to load scan data.");
      return;
    }
    hideError();
    if (data.last_error) {
      showError(`Last poll had an error (showing most recent good data): ${data.last_error}`);
    }
    state.lastUpdated = data.last_updated;
    render(data);
  } catch (err) {
    showError(`Could not reach the scanner backend: ${err.message}`);
  }
}

function showError(msg) {
  const banner = el("errorBanner");
  banner.textContent = msg;
  banner.hidden = false;
}
function hideError() {
  el("errorBanner").hidden = true;
}

function renderExpiries(data) {
  const select = el("expirySelect");
  const current = state.expiry || data.expiry;
  const options = data.all_expiries && data.all_expiries.length ? data.all_expiries : [data.expiry];
  select.innerHTML = options
    .filter(Boolean)
    .map((exp) => `<option value="${exp}" ${exp === current ? "selected" : ""}>${exp}</option>`)
    .join("");
}

function renderSummary(data) {
  const tiles = [
    ["Spot", fmt(data.spot)],
    ["ATM Strike", fmt(data.atm_strike, 0)],
    ["Days to Expiry", data.days_to_expiry ?? "—"],
    ["ATM IV", data.atm_iv !== null ? `${fmt(data.atm_iv)}%` : "—"],
    ["Total Call OI", fmt(data.total_call_oi, 0)],
    ["Total Put OI", fmt(data.total_put_oi, 0)],
    ["OI PCR", fmt(data.pcr)],
  ];
  el("summary").innerHTML = tiles
    .map(([label, value]) => `<div class="tile"><div class="tile__label">${label}</div><div class="tile__value">${value}</div></div>`)
    .join("");
}

function candidateCard(title, row) {
  if (!row) {
    return `<div class="candidate-card"><div class="candidate-card__title">${title}</div><p class="candidate-card__empty">No eligible candidate under the current filters.</p></div>`;
  }
  return `
    <div class="candidate-card">
      <div class="candidate-card__head">
        <span class="candidate-card__title">${title}</span>
        ${scoreBadge(row.score)}
      </div>
      <div class="candidate-card__contract">NIFTY ${fmt(row.strike, 0)} ${row.type}</div>
      <div class="candidate-card__grid">
        <div><span>IV</span>${fmt(row.iv)}%</div>
        <div><span>Theta Efficiency</span>${fmt(row.theta_efficiency_pct)}%</div>
        <div><span>OI</span>${fmt(row.oi, 0)}</div>
        <div><span>Delta</span>${fmt(row.delta, 2)}</div>
        <div><span>Breakeven</span>${fmt(row.breakeven)}</div>
        <div><span>BE Distance</span>${fmt(row.breakeven_distance_pct)}%</div>
      </div>
    </div>`;
}

function renderCandidates(data) {
  el("candidates").innerHTML =
    candidateCard("Call Selling Candidate", data.top_call) + candidateCard("Put Selling Candidate", data.top_put);
}

const COMPONENTS = [
  ["iv", "Relative IV", "iv_percentile"],
  ["theta", "Theta Efficiency", "theta_percentile"],
  ["oi", "Open Interest", "oi_percentile"],
  ["oi_activity", "OI Activity", "oi_activity_percentile"],
];

function breakdownRow(r, weights, colSpan) {
  if (!r.eligible || r.score === null) return "";
  const bars = COMPONENTS.map(([key, label, pctKey]) => {
    const pct = r[pctKey] ?? 0;
    const weight = (weights?.[key] ?? 0) * 100;
    const contribution = (pct * (weights?.[key] ?? 0)).toFixed(1);
    return `
      <div class="breakdown__item">
        <div class="breakdown__label">${label} <span>${weight.toFixed(0)}% weight</span></div>
        <div class="breakdown__track"><div class="breakdown__fill" style="width:${Math.max(pct, 0)}%"></div></div>
        <div class="breakdown__value">${fmt(pct, 1)} pctl → <strong>${contribution}</strong> pts</div>
      </div>`;
  }).join("");

  return `
    <tr class="breakdown-row" data-breakdown-for="${r.ref_id}" hidden>
      <td colspan="${colSpan}">
        <div class="breakdown">
          <div class="breakdown__head">
            Why <strong>${fmt(r.strike, 0)} ${r.type}</strong> scored ${fmt(r.score, 1)} — percentile rank against the other eligible ${r.type} contracts, weighted:
          </div>
          <div class="breakdown__grid">${bars}</div>
          <p class="breakdown__foot">Percentiles are computed across the currently eligible ${r.type} contracts only, so they shift as you change the filters.</p>
        </div>
      </td>
    </tr>`;
}

function renderTable(data) {
  const colSpan = document.querySelectorAll("#scanTable thead th").length;
  el("scanBody").innerHTML = data.rows
    .map((r) => `
      <tr class="${r.eligible ? "expandable" : "ineligible"}" data-ref-id="${r.ref_id}">
        <td>${fmt(r.strike, 0)}</td>
        <td class="type-${r.type.toLowerCase()}">${r.type}</td>
        <td>${fmt(r.ltp)}</td>
        <td>${fmt(r.iv)}</td>
        <td>${fmtSigned(r.iv_vs_atm)}</td>
        <td>${fmt(r.oi, 0)}</td>
        <td>${fmtSigned(r.oi_change_abs, 0)}${r.oi_change_pct !== null ? ` (${fmtSigned(r.oi_change_pct)}%)` : ""}</td>
        <td>${fmt(r.volume, 0)}</td>
        <td>${fmt(r.delta, 2)}</td>
        <td>${fmt(r.theta, 2)}</td>
        <td>${fmt(r.theta_efficiency_pct)}</td>
        <td>${fmt(r.gamma, 4)}</td>
        <td>${fmt(r.vega, 2)}</td>
        <td>${fmt(r.distance_pct)}</td>
        <td>${fmt(r.breakeven)}</td>
        <td>${fmt(r.breakeven_distance_pct)}</td>
        <td>${scoreBadge(r.score)}</td>
      </tr>
      ${breakdownRow(r, data.weights, colSpan)}`)
    .join("");

  // Re-open whichever breakdown the user had expanded, so a 5s refresh doesn't
  // collapse it mid-explanation.
  if (state.expandedRefId !== null) {
    const detail = document.querySelector(`[data-breakdown-for="${state.expandedRefId}"]`);
    if (detail) detail.hidden = false;
  }
}

function renderStatus() {
  const dot = el("statusDot");
  const text = el("statusText");
  if (!state.lastUpdated) {
    dot.className = "status__dot";
    text.textContent = "connecting…";
    return;
  }
  const secondsAgo = Math.max(0, Math.round((Date.now() - new Date(state.lastUpdated).getTime()) / 1000));
  dot.className = "status__dot " + (secondsAgo < 10 ? "fresh" : secondsAgo < 30 ? "aging" : "stale");
  text.textContent = `updated ${secondsAgo}s ago`;
}

function render(data) {
  renderExpiries(data);
  renderSummary(data);
  renderCandidates(data);
  renderTable(data);
  renderCharts(data);
  renderStatus();
}

function bindTableExpansion() {
  el("scanBody").addEventListener("click", (e) => {
    const row = e.target.closest("tr.expandable");
    if (!row) return;
    const refId = row.dataset.refId;
    const detail = document.querySelector(`[data-breakdown-for="${refId}"]`);
    if (!detail) return;

    const wasOpen = !detail.hidden;
    document.querySelectorAll(".breakdown-row").forEach((d) => { d.hidden = true; });
    detail.hidden = wasOpen;
    state.expandedRefId = wasOpen ? null : refId;
  });
}

function bindControls() {
  el("sideSelect").addEventListener("change", (e) => { state.side = e.target.value; fetchScan(); });
  el("deltaMin").addEventListener("change", (e) => { state.deltaMin = parseFloat(e.target.value) || 0; fetchScan(); });
  el("deltaMax").addEventListener("change", (e) => { state.deltaMax = parseFloat(e.target.value) || 1; fetchScan(); });
  el("minOi").addEventListener("change", (e) => { state.minOi = parseInt(e.target.value, 10) || 0; fetchScan(); });
  el("minVolume").addEventListener("change", (e) => { state.minVolume = parseInt(e.target.value, 10) || 0; fetchScan(); });
  el("expirySelect").addEventListener("change", (e) => {
    state.expiry = e.target.value;
    showError("Switching expiry — the next refresh (within a few seconds) will reflect it.");
    fetchScan();
  });
}

bindControls();
bindTableExpansion();
fetchScan();
setInterval(fetchScan, REFRESH_MS);
setInterval(renderStatus, 1000);
