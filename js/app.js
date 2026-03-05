const DATA_URL = './data/claude_commits.json';

function formatNumber(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(n >= 10000000 ? 0 : 1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k';
  return n.toLocaleString();
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

  const daily = data.daily || {};
  const dates = Object.keys(daily).sort();
  if (dates.length === 0) {
    loadingEl.className = 'error';
    loadingEl.textContent = 'No data available yet. Run scripts/update_claude_commits.py first.';
    return;
  }

  const values = dates.map(d => daily[d]);
  const today = dates[dates.length - 1];
  const yesterday = dates.length >= 2 ? dates[dates.length - 2] : today;
  const todayCount = daily[today] ?? 0;
  const yesterdayCount = daily[yesterday] ?? 0;
  const totalCommits = data.metadata?.total_commits ?? values.reduce((a, b) => a + b, 0);

  appEl.innerHTML = `
    <div class="metrics">
      <div class="metric-card">
        <div class="label">Today (${today})</div>
        <div class="value orange">${formatNumber(todayCount)}</div>
      </div>
      <div class="metric-card">
        <div class="label">Yesterday (${yesterday})</div>
        <div class="value orange">${formatNumber(yesterdayCount)}</div>
      </div>
      <div class="metric-card">
        <div class="label">Cumulative Total</div>
        <div class="value">${formatNumber(totalCommits)}</div>
      </div>
    </div>

    <div class="chart-container">
      <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background: #E87B5A; height: 3px;"></div>Daily Claude Commits</div>
        <button id="resetZoom">Reset Zoom</button>
      </div>
      <div class="chart-wrapper">
        <canvas id="chart"></canvas>
      </div>
    </div>

    <footer>
      Last updated: ${data.last_updated ? new Date(data.last_updated).toLocaleString() : 'N/A'}
      &nbsp;&middot;&nbsp; ${dates.length} days tracked<br>
      Data sourced from GitHub Search API
    </footer>
  `;

  const ctx = document.getElementById('chart').getContext('2d');
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: dates,
      datasets: [
        {
          label: 'Daily Claude Commits',
          data: values,
          borderColor: '#E87B5A',
          backgroundColor: 'rgba(232, 123, 90, 0.1)',
          borderWidth: 2.5,
          pointRadius: 0,
          pointHitRadius: 6,
          tension: 0,
          fill: true,
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
        legend: { display: false },
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
              return `Commits: ${ctx.raw.toLocaleString()}`;
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
            displayFormats: { month: 'MMM yyyy' },
          },
          grid: { color: 'rgba(75, 85, 99, 0.3)' },
          ticks: {
            color: '#9CA3AF',
            font: { size: 11 },
            maxRotation: 0,
          },
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(75, 85, 99, 0.3)' },
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
