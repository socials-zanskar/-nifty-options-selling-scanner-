/* Inline-SVG charts. No libraries, no build step -- the dashboard is served as
   static files, so everything here is hand-rolled against the /api/scan payload. */

const CHART_W = 720;
const CHART_H = 250;
const M = { top: 16, right: 18, bottom: 34, left: 52 };

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function chartColors() {
  return {
    ce: css("--series-1"),
    pe: css("--series-2"),
    grid: css("--gridline"),
    axis: css("--baseline"),
    muted: css("--muted"),
    text: css("--text-secondary"),
    surface: css("--surface"),
  };
}

function scaleLinear(domain, range) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

function niceTicks(min, max, count = 5) {
  if (min === max) return [min];
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const ticks = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(Number(t.toFixed(10)));
  return ticks;
}

function legend(items) {
  return `<div class="chart__legend">${items
    .map((it) => `<span class="chart__legend-item"><span class="chart__swatch" style="background:${it.color}"></span>${it.label}</span>`)
    .join("")}</div>`;
}

/* --- shared tooltip ------------------------------------------------------- */

let tipEl = null;
function tooltip() {
  if (!tipEl) {
    tipEl = document.createElement("div");
    tipEl.className = "chart-tooltip";
    tipEl.hidden = true;
    document.body.appendChild(tipEl);
  }
  return tipEl;
}

function bindMarkTooltips(root) {
  const tip = tooltip();
  root.querySelectorAll("[data-tip]").forEach((mark) => {
    mark.addEventListener("mouseenter", (e) => {
      tip.innerHTML = e.currentTarget.getAttribute("data-tip");
      tip.hidden = false;
    });
    mark.addEventListener("mousemove", (e) => {
      tip.style.left = `${e.clientX + 14}px`;
      tip.style.top = `${e.clientY + 14}px`;
    });
    mark.addEventListener("mouseleave", () => { tip.hidden = true; });
  });
}

/* --- line/dot chart by strike (IV smile, theta efficiency) ---------------- */

function lineChartByStrike(rows, { valueKey, valueLabel, valueSuffix, atmStrike, highlightIds }) {
  const c = chartColors();
  const points = rows.filter((r) => r[valueKey] !== null && r[valueKey] !== undefined && r.strike !== null);
  if (!points.length) return `<p class="chart__empty">No data for this view.</p>`;

  const strikes = points.map((p) => p.strike);
  const values = points.map((p) => p[valueKey]);
  const xMin = Math.min(...strikes), xMax = Math.max(...strikes);
  const yMinRaw = Math.min(...values), yMaxRaw = Math.max(...values);
  const pad = (yMaxRaw - yMinRaw) * 0.15 || Math.abs(yMaxRaw * 0.1) || 1;
  const yMin = yMinRaw - pad, yMax = yMaxRaw + pad;

  const x = scaleLinear([xMin, xMax], [M.left, CHART_W - M.right]);
  const y = scaleLinear([yMin, yMax], [CHART_H - M.bottom, M.top]);

  const yTicks = niceTicks(yMin, yMax, 4);
  const xTicks = niceTicks(xMin, xMax, 6).filter((t) => t >= xMin && t <= xMax);

  const grid = yTicks
    .map((t) => `<line x1="${M.left}" x2="${CHART_W - M.right}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}" stroke="${c.grid}" stroke-width="1"/>`)
    .join("");

  const yLabels = yTicks
    .map((t) => `<text x="${M.left - 8}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end" fill="${c.muted}" font-size="11">${t}</text>`)
    .join("");

  const xLabels = xTicks
    .map((t) => `<text x="${x(t).toFixed(1)}" y="${CHART_H - M.bottom + 18}" text-anchor="middle" fill="${c.muted}" font-size="11">${t.toLocaleString("en-IN")}</text>`)
    .join("");

  const atmLine =
    atmStrike && atmStrike >= xMin && atmStrike <= xMax
      ? `<line x1="${x(atmStrike).toFixed(1)}" x2="${x(atmStrike).toFixed(1)}" y1="${M.top}" y2="${CHART_H - M.bottom}" stroke="${c.axis}" stroke-width="1" stroke-dasharray="4 3"/>
         <text x="${x(atmStrike).toFixed(1)}" y="${M.top - 4}" text-anchor="middle" fill="${c.muted}" font-size="10">ATM</text>`
      : "";

  let marks = "";
  for (const side of ["CE", "PE"]) {
    const sidePoints = points.filter((p) => p.type === side).sort((a, b) => a.strike - b.strike);
    if (!sidePoints.length) continue;
    const color = side === "CE" ? c.ce : c.pe;
    const path = sidePoints.map((p, i) => `${i ? "L" : "M"}${x(p.strike).toFixed(1)},${y(p[valueKey]).toFixed(1)}`).join(" ");
    marks += `<path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
    // A full chain packs 60+ strikes into this width, where full-size dots merge
    // into a solid band -- shrink them as the series gets denser.
    const dotR = sidePoints.length > 40 ? 2 : sidePoints.length > 22 ? 3 : 4.5;
    marks += sidePoints
      .map((p) => {
        const isTop = highlightIds.includes(p.ref_id);
        const tip = `<strong>${p.strike.toLocaleString("en-IN")} ${p.type}</strong><br/>${valueLabel}: ${p[valueKey]}${valueSuffix}`;
        return `<circle cx="${x(p.strike).toFixed(1)}" cy="${y(p[valueKey]).toFixed(1)}" r="${isTop ? 7 : dotR}"
                  fill="${color}" stroke="${c.surface}" stroke-width="${isTop ? 2 : dotR >= 4 ? 2 : 0}" data-tip="${tip}" style="cursor:pointer"/>`;
      })
      .join("");
  }

  return `
    <svg viewBox="0 0 ${CHART_W} ${CHART_H}" class="chart__svg" role="img" aria-label="${valueLabel} by strike">
      ${grid}${atmLine}
      <line x1="${M.left}" x2="${CHART_W - M.right}" y1="${CHART_H - M.bottom}" y2="${CHART_H - M.bottom}" stroke="${c.axis}" stroke-width="1"/>
      ${yLabels}${xLabels}${marks}
    </svg>`;
}

/* --- diverging OI bars (calls left, puts right) --------------------------- */

/* A real chain runs to 60+ strikes; drawing them all makes a chart taller than
   the screen. Show a window around ATM instead -- and say how many were left
   out, so the truncation is never silent. */
const OI_MAX_ROWS = 18;
const OI_W = 1300;   // wide viewBox: near-1:1 render scale, so rows stay compact

function oiByStrikeChart(rows, atmStrike) {
  const c = chartColors();
  const byStrike = new Map();
  for (const r of rows) {
    if (r.strike === null || r.oi === null) continue;
    if (!byStrike.has(r.strike)) byStrike.set(r.strike, { strike: r.strike, ce: 0, pe: 0 });
    byStrike.get(r.strike)[r.type.toLowerCase()] = r.oi;
  }
  const all = [...byStrike.values()];
  if (!all.length) return { svg: `<p class="chart__empty">No data for this view.</p>`, shown: 0, total: 0 };

  let data = all;
  if (all.length > OI_MAX_ROWS) {
    const pivot = atmStrike ?? all[Math.floor(all.length / 2)].strike;
    data = [...all]
      .sort((a, b) => Math.abs(a.strike - pivot) - Math.abs(b.strike - pivot))
      .slice(0, OI_MAX_ROWS);
  }
  data.sort((a, b) => b.strike - a.strike);

  const maxOi = Math.max(...data.flatMap((d) => [d.ce, d.pe])) || 1;
  const rowH = 22;
  const height = M.top + data.length * rowH + M.bottom;
  const centerLabelW = 78;
  const half = (OI_W - centerLabelW) / 2 - M.right;

  const bars = data
    .map((d, i) => {
      const yPos = M.top + i * rowH;
      const ceW = (d.ce / maxOi) * half;
      const peW = (d.pe / maxOi) * half;
      const centerL = half;
      const centerR = half + centerLabelW;
      // 2px surface gap between the bar and the centre label keeps the two
      // sides visually separate (dataviz spacer rule)
      const ceTip = `<strong>${d.strike.toLocaleString("en-IN")} CE</strong><br/>OI: ${d.ce.toLocaleString("en-IN")}`;
      const peTip = `<strong>${d.strike.toLocaleString("en-IN")} PE</strong><br/>OI: ${d.pe.toLocaleString("en-IN")}`;
      return `
        <rect x="${centerL - ceW}" y="${yPos}" width="${Math.max(ceW - 2, 0)}" height="${rowH - 6}" rx="3" fill="${c.ce}" data-tip="${ceTip}" style="cursor:pointer"/>
        <rect x="${centerR + 2}" y="${yPos}" width="${Math.max(peW - 2, 0)}" height="${rowH - 6}" rx="3" fill="${c.pe}" data-tip="${peTip}" style="cursor:pointer"/>
        <text x="${centerL + centerLabelW / 2}" y="${yPos + rowH - 10}" text-anchor="middle" fill="${c.text}" font-size="11">${d.strike.toLocaleString("en-IN")}</text>`;
    })
    .join("");

  return {
    svg: `<svg viewBox="0 0 ${OI_W} ${height}" class="chart__svg" role="img" aria-label="Open interest by strike, calls versus puts">${bars}</svg>`,
    shown: data.length,
    total: all.length,
  };
}

/* --- public entry point --------------------------------------------------- */

function renderCharts(data) {
  const rows = data.rows || [];
  const highlightIds = [data.top_call?.ref_id, data.top_put?.ref_id].filter((v) => v !== undefined && v !== null);
  const c = chartColors();
  const seriesLegend = legend([
    { label: "Calls (CE)", color: c.ce },
    { label: "Puts (PE)", color: c.pe },
  ]);

  const oi = oiByStrikeChart(rows, data.atm_strike);
  const container = document.getElementById("charts");
  container.innerHTML = `
    <figure class="chart">
      <figcaption class="chart__title">IV Smile <span class="chart__note">larger dots = top-ranked candidate</span></figcaption>
      ${seriesLegend}
      ${lineChartByStrike(rows, { valueKey: "iv", valueLabel: "IV", valueSuffix: "%", atmStrike: data.atm_strike, highlightIds })}
    </figure>
    <figure class="chart">
      <figcaption class="chart__title">Theta Efficiency by Strike</figcaption>
      ${seriesLegend}
      ${lineChartByStrike(rows, { valueKey: "theta_efficiency_pct", valueLabel: "Theta efficiency", valueSuffix: "%", atmStrike: data.atm_strike, highlightIds })}
    </figure>
    <figure class="chart chart--wide">
      <figcaption class="chart__title">Open Interest by Strike${oi.total > oi.shown ? `<span class="chart__note">${oi.shown} strikes nearest ATM (of ${oi.total})</span>` : ""}</figcaption>
      ${seriesLegend}
      ${oi.svg}
    </figure>`;

  bindMarkTooltips(container);
}

window.renderCharts = renderCharts;
