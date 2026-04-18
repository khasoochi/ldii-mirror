// Home dashboard charts. All charts are vertical bars with hidden x-axis
// labels — the full Devanagari name appears on hover. Canvases live inside
// fixed-height .chart-box wrappers to prevent the Chart.js resize feedback
// loop.

(function () {
  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }
  function whenChart(cb) {
    if (window.Chart) return cb();
    const t = setInterval(() => { if (window.Chart) { clearInterval(t); cb(); } }, 30);
  }
  function idle(fn) {
    if (window.requestIdleCallback) requestIdleCallback(fn, { timeout: 600 });
    else setTimeout(fn, 50);
  }
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function themeColors() {
    return {
      accent: cssVar("--accent"),
      accentWeak: cssVar("--accent-weak"),
      bgElev: cssVar("--bg-elev"),
      fg: cssVar("--fg"),
      fgSoft: cssVar("--fg-soft"),
      fgDim: cssVar("--fg-dim"),
      grid: cssVar("--border"),
    };
  }

  function verticalBarOptions(c, labels, { onClick } = {}) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600, easing: "easeOutCubic" },
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: c.bgElev,
          titleColor: c.fg, bodyColor: c.fgSoft,
          borderColor: c.grid, borderWidth: 1,
          cornerRadius: 8, padding: 10,
          displayColors: false,
          callbacks: {
            title: (items) => items.length ? labels[items[0].dataIndex] : "",
            label: (item) => `${item.formattedValue} manuscripts`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false, drawBorder: false },
          ticks: { display: false },
        },
        y: {
          grid: { color: c.grid, drawBorder: false },
          ticks: { color: c.fgDim, precision: 0 },
          beginAtZero: true,
        },
      },
      onClick,
    };
  }

  function bar(el, labels, values, c, onClick) {
    return new Chart(el, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: c.accent,
          hoverBackgroundColor: cssVar("--fg"),
          borderRadius: 4,
          maxBarThickness: 40,
        }],
      },
      options: verticalBarOptions(c, labels, { onClick }),
    });
  }

  function drawCharts(stats) {
    const c = themeColors();

    const langs = stats.top_languages;
    bar(
      document.getElementById("chart-lang"),
      langs.map(x => x.name), langs.map(x => x.count), c,
      (_, els) => { if (els.length) window.location.href = "/languages/" + encodeURIComponent(langs[els[0].index].name); },
    );

    const subs = stats.top_subjects;
    bar(
      document.getElementById("chart-subjects"),
      subs.map(x => x.name), subs.map(x => x.count), c,
      (_, els) => { if (els.length) window.location.href = "/subjects/" + encodeURIComponent(subs[els[0].index].name); },
    );

    const auths = stats.top_authors;
    bar(
      document.getElementById("chart-authors"),
      auths.map(x => x.name), auths.map(x => x.count), c,
      (_, els) => { if (els.length) window.location.href = "/authors/" + encodeURIComponent(auths[els[0].index].name); },
    );

    const conds = stats.condition_distribution;
    bar(
      document.getElementById("chart-condition"),
      conds.map(x => x.name), conds.map(x => x.count), c,
      (_, els) => { if (els.length) window.location.href = "/browse?condition=" + encodeURIComponent(conds[els[0].index].name); },
    );

    const cents = stats.century_distribution;
    const centLabels = cents.map(x => x.century + "c");
    new Chart(document.getElementById("chart-century"), {
      type: "bar",
      data: {
        labels: centLabels,
        datasets: [{
          data: cents.map(x => x.count),
          backgroundColor: c.accent,
          hoverBackgroundColor: cssVar("--fg"),
          borderRadius: 4,
          maxBarThickness: 30,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 600 },
        interaction: { mode: "nearest", axis: "x", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: c.bgElev, titleColor: c.fg, bodyColor: c.fgSoft,
            borderColor: c.grid, borderWidth: 1, cornerRadius: 8, padding: 10,
            displayColors: false,
            callbacks: {
              title: (items) => {
                const n = cents[items[0].dataIndex].century;
                const suffix = ["th","st","nd","rd"][((n % 100 - 20) % 10 + 10) % 10] || (n % 100 >= 11 && n % 100 <= 13 ? "th" : "th");
                return `${n}${suffix} century`;
              },
              label: (item) => `${item.formattedValue} manuscripts`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: c.fgDim, font: { size: 11 } } },
          y: { grid: { color: c.grid }, ticks: { color: c.fgDim, precision: 0 }, beginAtZero: true },
        },
        onClick: (_, els) => {
          if (!els.length) return;
          window.location.href = "/browse?century=" + cents[els[0].index].century;
        },
      },
    });
  }

  function animateCounts() {
    document.querySelectorAll("[data-count]").forEach(el => {
      const n = parseInt(el.getAttribute("data-count"), 10);
      if (isFinite(n) && window.LDII) window.LDII.animateCount(el, n);
    });
  }

  function loadRandom() {
    const box = document.getElementById("random-strip");
    if (!box) return;
    box.innerHTML = Array(6).fill('<div class="mini-card"><div class="skeleton" style="height:18px;margin-bottom:8px;"></div><div class="skeleton" style="height:12px;width:60%;"></div></div>').join("");
    fetch("/api/random?n=6").then(r => r.json()).then(data => {
      box.innerHTML = data.rows.map(r => `
        <a class="mini-card" href="/manuscript/${encodeURIComponent(r.manuscript_number)}">
          <div class="mini-title">${LDII.escapeHtml(r.title || '—')}</div>
          <div class="muted" style="font-size:.88rem;">${LDII.escapeHtml(r.author || '—')}</div>
          <div class="mt-8 flex wrap gap-8">
            ${r.year_of_writing ? `<span class="badge">${LDII.escapeHtml(r.year_of_writing)}</span>` : ''}
            ${r.language ? `<span class="chip">${LDII.escapeHtml(r.language)}</span>` : ''}
            ${r.subject ? `<span class="chip">${LDII.escapeHtml(r.subject)}</span>` : ''}
          </div>
        </a>
      `).join("");
    });
  }

  ready(() => {
    animateCounts();
    loadRandom();
    const btn = document.getElementById("reshuffle");
    if (btn) btn.addEventListener("click", loadRandom);

    idle(() => whenChart(() => {
      fetch("/api/stats").then(r => r.json()).then(drawCharts);
    }));
  });
})();
