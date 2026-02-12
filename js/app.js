const DATA_URL = './data/ai_docs_index.json';

function formatNumber(n) {
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k';
  return n.toLocaleString();
}

function defaultMarkers() {
  return {
    claude: 'CLAUDE.md',
    gemini: 'GEMINI.md',
    agents: 'AGENTS.md',
  };
}

function collectDates(seriesByKey, keys) {
  const datesSet = new Set();
  keys.forEach(key => {
    const series = seriesByKey[key] || {};
    Object.keys(series).forEach(d => datesSet.add(d));
  });
  return Array.from(datesSet).sort();
}

function alignSeries(dates, series) {
  return dates.map(d => series[d] ?? 0);
}

function sumValues(values) {
  return values.reduce((a, b) => a + b, 0);
}

async function main() {
  const appEl = document.getElementById('app');
  const loadingEl = document.getElementById('loading');

  let data;
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (e) {
    loadingEl.className = 'error';
    loadingEl.textContent = `Failed to load data: ${e.message}`;
    return;
  }

  const markers = { ...defaultMarkers(), ...(data.metadata?.markers || {}) };
  const markerKeys = ['claude', 'gemini', 'agents'];
  const seriesByKey = data.series || {};
  const dates = collectDates(seriesByKey, markerKeys);
  if (dates.length === 0) {
    loadingEl.className = 'error';
    loadingEl.textContent = 'No marker data available yet. Run scripts/update_doc_markers.py first.';
    return;
  }

  const valuesByKey = {};
  markerKeys.forEach(key => {
    valuesByKey[key] = alignSeries(dates, seriesByKey[key] || {});
  });

  // Metrics
  const today = dates[dates.length - 1];
  const yesterdayDate = dates.length >= 2 ? dates[dates.length - 2] : today;
  const todayClaude = seriesByKey.claude?.[today] ?? 0;
  const todayGemini = seriesByKey.gemini?.[today] ?? 0;
  const todayAgents = seriesByKey.agents?.[today] ?? 0;
  const yClaude = seriesByKey.claude?.[yesterdayDate] ?? 0;
  const yGemini = seriesByKey.gemini?.[yesterdayDate] ?? 0;
  const yAgents = seriesByKey.agents?.[yesterdayDate] ?? 0;
  const totalClaude = data.totals?.claude ?? sumValues(valuesByKey.claude);
  const totalGemini = data.totals?.gemini ?? sumValues(valuesByKey.gemini);
  const totalAgents = data.totals?.agents ?? sumValues(valuesByKey.agents);

  // Build UI
  appEl.innerHTML = `
    <div class="metrics">
      <div class="metric-card">
        <div class="label">Claude (${markers.claude})</div>
        <div class="value orange">${formatNumber(todayClaude)}</div>
        <div class="label">Yesterday ${formatNumber(yClaude)}</div>
      </div>
      <div class="metric-card">
        <div class="label">Gemini (${markers.gemini})</div>
        <div class="value" style="color: #5B8DEF;">${formatNumber(todayGemini)}</div>
        <div class="label">Yesterday ${formatNumber(yGemini)}</div>
      </div>
      <div class="metric-card">
        <div class="label">ChatGPT/Agents (${markers.agents})</div>
        <div class="value" style="color: #10B981;">${formatNumber(todayAgents)}</div>
        <div class="label">Yesterday ${formatNumber(yAgents)}</div>
      </div>
      <div class="metric-card">
        <div class="label">Total Unique Repos</div>
        <div class="value">${formatNumber(totalClaude + totalGemini + totalAgents)}</div>
        <div class="label">Claude ${formatNumber(totalClaude)} · Gemini ${formatNumber(totalGemini)} · ChatGPT/Agents ${formatNumber(totalAgents)}</div>
      </div>
    </div>

    <div class="chart-container">
      <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background: #E87B5A; height: 3px;"></div>Claude (${markers.claude})</div>
        <div class="legend-item"><div class="legend-color" style="background: #5B8DEF; height: 3px;"></div>Gemini (${markers.gemini})</div>
        <div class="legend-item"><div class="legend-color" style="background: #10B981; height: 3px;"></div>ChatGPT/Agents (${markers.agents})</div>
        <button id="resetZoom">Reset Zoom</button>
      </div>
      <div class="chart-wrapper">
        <canvas id="chart"></canvas>
      </div>
    </div>

    <footer>
      Last updated: ${data.last_updated ? new Date(data.last_updated).toLocaleString() : 'N/A'}
      &nbsp;·&nbsp; ${dates.length} days tracked<br>
      Single chart with 3 daily-new-repo lines (global dedupe, non-cumulative)<br>
      Data sourced from GitHub Search API (marker files in repositories)
    </footer>
  `;

  // Chart
  const ctx = document.getElementById('chart').getContext('2d');
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: dates,
      datasets: [
        {
          label: `Claude (${markers.claude})`,
          data: valuesByKey.claude,
          borderColor: '#E87B5A',
          borderWidth: 2.5,
          pointRadius: 0,
          pointHitRadius: 6,
          tension: 0,
          fill: false,
          order: 3,
        },
        {
          label: `Gemini (${markers.gemini})`,
          data: valuesByKey.gemini,
          borderColor: '#5B8DEF',
          borderWidth: 2.2,
          pointRadius: 0,
          pointHitRadius: 6,
          tension: 0.1,
          fill: false,
          order: 2,
        },
        {
          label: `ChatGPT/Agents (${markers.agents})`,
          data: valuesByKey.agents,
          borderColor: '#10B981',
          borderWidth: 2.2,
          pointRadius: 0,
          pointHitRadius: 6,
          tension: 0.1,
          fill: false,
          order: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          backgroundColor: '#1A1D27',
          titleColor: '#F9FAFB',
          bodyColor: '#D1D5DB',
          borderColor: '#374151',
          borderWidth: 1,
          padding: 12,
          callbacks: {
            title: function(context) {
              const date = new Date(context[0].parsed.x);
              return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
            },
            label: function(ctx) {
              if (ctx.raw === null) return null;
              const val = typeof ctx.raw === 'number' ? ctx.raw.toLocaleString(undefined, { maximumFractionDigits: 0 }) : ctx.raw;
              return `${ctx.dataset.label}: ${val}`;
            },
          },
        },
        zoom: {
          zoom: {
            wheel: { enabled: true },
            pinch: { enabled: true },
            mode: 'x',
          },
          pan: {
            enabled: true,
            mode: 'x',
          },
          limits: {
            x: {
              min: new Date(dates[0]).getTime(),
              max: new Date(today).getTime() + 86400000,
              minRange: 7 * 86400000,
            },
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          min: dates[0],
          max: today,
          time: {
            unit: 'month',
            displayFormats: {
              month: 'MMM yyyy',
            },
          },
          grid: {
            color: 'rgba(75, 85, 99, 0.3)',
          },
          ticks: {
            color: '#9CA3AF',
            font: { size: 11 },
            maxRotation: 0,
          },
        },
        y: {
          beginAtZero: true,
          grid: {
            color: 'rgba(75, 85, 99, 0.3)',
          },
          ticks: {
            color: '#9CA3AF',
            font: { size: 11 },
            callback: function(value) {
              if (value >= 1000) return (value / 1000) + 'k';
              return value;
            },
          },
        },
      },
    },
  });

  document.getElementById('resetZoom').addEventListener('click', () => chart.resetZoom());
}

main();
