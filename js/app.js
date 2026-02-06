const DATA_URL = './data/contributions.json';

function formatNumber(n) {
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k';
  return n.toLocaleString();
}

function computeMA(values, period) {
  const result = [];
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) {
        sum += values[j];
      }
      result.push(sum / period);
    }
  }
  return result;
}

function computeYTDGrowth(dates, values) {
  const now = new Date();
  const yearStart = now.getFullYear() + '-01-01';
  const yearDates = [];
  const yearValues = [];
  for (let i = 0; i < dates.length; i++) {
    if (dates[i] >= yearStart) {
      yearDates.push(dates[i]);
      yearValues.push(values[i]);
    }
  }
  if (yearValues.length < 28) return null; // need at least 4 weeks
  const firstWeek = yearValues.slice(0, 7);
  const lastWeek = yearValues.slice(-7);
  const firstAvg = firstWeek.reduce((a, b) => a + b, 0) / firstWeek.length;
  const lastAvg = lastWeek.reduce((a, b) => a + b, 0) / lastWeek.length;
  if (firstAvg === 0) return null;
  return ((lastAvg - firstAvg) / firstAvg) * 100;
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

  const contributions = data.contributions || {};
  const dates = Object.keys(contributions).sort();
  if (dates.length === 0) {
    loadingEl.className = 'error';
    loadingEl.textContent = 'No contribution data available yet. Run initial_scrape.py first.';
    return;
  }

  const values = dates.map(d => contributions[d]);
  const ma20 = computeMA(values, 20);
  const ma60 = computeMA(values, 60);
  const ma200 = computeMA(values, 200);

  // Filter display data to start from START_DATE
  const START_DATE = '2024-03-01';
  const startIdx = dates.findIndex(d => d >= START_DATE);
  const displayDates = dates.slice(startIdx);
  const displayValues = values.slice(startIdx);
  const displayMa20 = ma20.slice(startIdx);
  const displayMa60 = ma60.slice(startIdx);
  const displayMa200 = ma200.slice(startIdx);

  // Metrics
  const today = new Date().toISOString().slice(0, 10);
  const yesterdayDate = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  const todayVal = contributions[today] ?? null;
  const yesterdayVal = contributions[yesterdayDate] ?? null;

  const last7 = values.slice(-7);
  const avg7 = last7.length > 0 ? last7.reduce((a, b) => a + b, 0) / last7.length : null;
  const ytdGrowth = computeYTDGrowth(dates, values);

  // Build UI
  appEl.innerHTML = `
    <div class="metrics">
      <div class="metric-card">
        <div class="label">Today (Live)</div>
        <div class="value orange">${todayVal !== null ? formatNumber(todayVal) : '—'}</div>
      </div>
      <div class="metric-card">
        <div class="label">Yesterday</div>
        <div class="value">${yesterdayVal !== null ? formatNumber(yesterdayVal) : '—'}</div>
      </div>
      <div class="metric-card">
        <div class="label">7-Day Average</div>
        <div class="value">${avg7 !== null ? formatNumber(Math.round(avg7)) : '—'}</div>
      </div>
      <div class="metric-card">
        <div class="label">YTD Growth</div>
        <div class="value ${ytdGrowth !== null ? (ytdGrowth >= 0 ? 'green' : 'red') : ''}">${ytdGrowth !== null ? (ytdGrowth >= 0 ? '+' : '') + ytdGrowth.toFixed(1) + '%' : '—'}</div>
      </div>
    </div>

    <div class="chart-container">
      <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background: #E87B5A; height: 3px;"></div>Daily Commits</div>
        <div class="legend-item"><div class="legend-color" style="background: #F0A888;"></div>20-Day MA</div>
        <div class="legend-item"><div class="legend-color" style="background: #5B8DEF;"></div>60-Day MA</div>
        <div class="legend-item"><div class="legend-color" style="background: #9CA3AF;"></div>200-Day MA</div>
        <button id="resetZoom">Reset Zoom</button>
      </div>
      <div class="chart-wrapper">
        <canvas id="chart"></canvas>
      </div>
    </div>

    <footer>
      Last updated: ${data.last_updated ? new Date(data.last_updated).toLocaleString() : 'N/A'}
      &nbsp;·&nbsp; ${displayDates.length} days tracked<br>
      Dates are based on commit author timezone<br>
      Data sourced from GitHub Search API for user @claude (ID: 81847)
    </footer>
  `;

  // Chart
  const ctx = document.getElementById('chart').getContext('2d');
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: displayDates,
      datasets: [
        {
          label: 'Daily Commits',
          data: displayValues,
          borderColor: '#E87B5A',
          borderWidth: 2.5,
          pointRadius: 0,
          pointHitRadius: 6,
          tension: 0,
          fill: false,
          order: 4,
        },
        {
          label: '20-Day MA',
          data: displayMa20,
          borderColor: '#F0A888',
          borderWidth: 1.5,
          pointRadius: 0,
          pointHitRadius: 6,
          tension: 0.3,
          fill: false,
          order: 3,
        },
        {
          label: '60-Day MA',
          data: displayMa60,
          borderColor: '#5B8DEF',
          borderWidth: 1.5,
          pointRadius: 0,
          pointHitRadius: 6,
          tension: 0.3,
          fill: false,
          order: 2,
        },
        {
          label: '200-Day MA',
          data: displayMa200,
          borderColor: '#9CA3AF',
          borderWidth: 1.5,
          pointRadius: 0,
          pointHitRadius: 6,
          tension: 0.3,
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
              min: new Date(START_DATE).getTime(),
              max: new Date(today).getTime() + 86400000,
              minRange: 7 * 86400000,
            },
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          min: START_DATE,
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
