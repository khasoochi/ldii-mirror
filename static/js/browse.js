// Browse page controller: reads filter/search/sort/pagination state,
// syncs it to the URL, fetches /api/manuscripts, renders a table.

(function () {
  const state = {
    q: "", author: "", subject: "", language: "", condition: "",
    century: "", year_from: "", year_to: "", has_commentary: "",
    sort: "manuscript_number", order: "asc",
    page: 1, per_page: 50,
  };
  const cache = new Map();  // query string -> response
  let inflight = null;

  function readURL() {
    const p = new URLSearchParams(location.search);
    for (const k of Object.keys(state)) {
      if (p.has(k)) state[k] = p.get(k);
    }
    state.page = parseInt(state.page, 10) || 1;
    state.per_page = parseInt(state.per_page, 10) || 50;
  }

  function writeURL() {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state)) {
      if (v !== "" && v !== null && v !== undefined && !(k === "page" && v === 1) &&
          !(k === "per_page" && v === 50) && !(k === "sort" && v === "manuscript_number") &&
          !(k === "order" && v === "asc")) {
        p.set(k, v);
      }
    }
    const qs = p.toString();
    const url = qs ? `?${qs}` : location.pathname;
    history.replaceState(null, "", url);
  }

  function paintMeta(total) {
    const el = document.getElementById("result-meta");
    const from = total === 0 ? 0 : (state.page - 1) * state.per_page + 1;
    const to = Math.min(total, state.page * state.per_page);
    el.textContent = total === 0
      ? "No manuscripts match the current filters."
      : `Showing ${LDII.fmt(from)}–${LDII.fmt(to)} of ${LDII.fmt(total)}`;
  }

  function renderRows(rows) {
    const body = document.getElementById("ms-body");
    if (!rows.length) { body.innerHTML = `<tr><td colspan="10" class="empty">No results.</td></tr>`; return; }
    body.innerHTML = rows.map(r => {
      const mid = encodeURIComponent(r.manuscript_number);
      const author = r.author ? `<a class="chip" href="/authors/${encodeURIComponent(r.author)}">${LDII.escapeHtml(r.author)}</a>` : '<span class="muted">—</span>';
      const subject = r.subject ? `<a class="chip" href="/subjects/${encodeURIComponent(r.subject)}">${LDII.escapeHtml(r.subject)}</a>` : '<span class="muted">—</span>';
      const lang = r.language ? `<a class="chip" href="/languages/${encodeURIComponent(r.language)}">${LDII.escapeHtml(r.language)}</a>` : '<span class="muted">—</span>';
      const year = r.year_of_writing ? `<span class="tabular">${LDII.escapeHtml(r.year_of_writing)}</span>` : '<span class="muted">—</span>';
      return `<tr>
        <td data-col="manuscript_number" class="num tabular">${LDII.escapeHtml(r.manuscript_number)}</td>
        <td data-col="title"><a class="title-link" href="/manuscript/${mid}">${LDII.escapeHtml(r.title || '—')}</a></td>
        <td data-col="author">${author}</td>
        <td data-col="subject">${subject}</td>
        <td data-col="language">${lang}</td>
        <td data-col="year_of_writing">${year}</td>
        <td data-col="condition" class="hidden-col">${LDII.escapeHtml(r.condition || '—')}</td>
        <td data-col="folio_number" class="hidden-col tabular">${LDII.escapeHtml(r.folio_number || '—')}</td>
        <td data-col="commentator" class="hidden-col">${LDII.escapeHtml(r.commentator || '—')}</td>
        <td data-col="commentary_name" class="hidden-col">${LDII.escapeHtml(r.commentary_name || '—')}</td>
      </tr>`;
    }).join("");
    applyColumnVisibility();
  }

  function renderPagination(total, pages) {
    const box = document.getElementById("pagination");
    box.innerHTML = "";
    if (pages <= 1) return;
    const add = (label, page, active, disabled) => {
      const btn = document.createElement("span");
      btn.className = "page" + (active ? " on" : "");
      btn.textContent = label;
      if (!active && !disabled) btn.addEventListener("click", () => { state.page = page; load(); });
      if (disabled) btn.style.opacity = .4;
      box.appendChild(btn);
    };
    const addEllip = () => {
      const s = document.createElement("span"); s.className = "ellip"; s.textContent = "…"; box.appendChild(s);
    };

    add("‹", Math.max(1, state.page - 1), false, state.page === 1);
    const window_ = 2;
    const start = Math.max(1, state.page - window_);
    const end = Math.min(pages, state.page + window_);
    if (start > 1) { add(1, 1, state.page === 1); if (start > 2) addEllip(); }
    for (let p = start; p <= end; p++) add(p, p, p === state.page);
    if (end < pages) { if (end < pages - 1) addEllip(); add(pages, pages, state.page === pages); }
    add("›", Math.min(pages, state.page + 1), false, state.page === pages);

    const info = document.createElement("span");
    info.className = "info";
    info.textContent = `Page ${state.page} of ${pages}`;
    box.appendChild(info);
  }

  function sortIndicators() {
    document.querySelectorAll("#ms-table thead th").forEach(th => {
      const s = th.getAttribute("data-sort");
      const ind = th.querySelector(".sort-ind") || (() => {
        const el = document.createElement("span"); el.className = "sort-ind"; el.textContent = "↕"; th.appendChild(el); return el;
      })();
      th.classList.toggle("sorted", s === state.sort);
      if (s === state.sort) ind.textContent = state.order === "asc" ? "↑" : "↓";
      else ind.textContent = "↕";
    });
  }

  function updateExportLink() {
    const a = document.getElementById("export-btn");
    a.href = "/api/export?" + LDII.buildQuery(state);
  }

  function load() {
    writeURL();
    sortIndicators();
    updateExportLink();
    const qs = LDII.buildQuery(state);

    if (cache.has(qs)) { paint(cache.get(qs)); return; }

    if (inflight) inflight.abort();
    const ctrl = new AbortController();
    inflight = ctrl;
    document.getElementById("result-meta").textContent = "Loading…";

    fetch("/api/manuscripts?" + qs, { signal: ctrl.signal })
      .then(r => r.json())
      .then(data => {
        cache.set(qs, data);
        if (cache.size > 30) cache.delete(cache.keys().next().value);
        paint(data);
      })
      .catch(e => { if (e.name !== "AbortError") console.error(e); });
  }

  function paint(data) {
    renderRows(data.rows);
    paintMeta(data.total);
    renderPagination(data.total, data.pages);
  }

  // ---- filter wiring ----
  function bindFilters() {
    const bind = (id, key, event = "change") => {
      const el = document.getElementById(id);
      if (!el) return;
      // hydrate from state
      if (el.type === "checkbox") el.checked = state[key] === "true" || state[key] === true;
      else el.value = state[key] ?? "";
      el.addEventListener(event, () => {
        if (el.type === "checkbox") state[key] = el.checked ? "true" : "";
        else state[key] = el.value.trim();
        state.page = 1;
        load();
      });
    };
    bind("f-language", "language");
    bind("f-subject", "subject");
    bind("f-condition", "condition");
    bind("f-century", "century");
    bind("f-commentary", "has_commentary");
    bind("f-author", "author", "change");
    bind("f-year-from", "year_from", "change");
    bind("f-year-to", "year_to", "change");

    const q = document.getElementById("q");
    q.value = state.q;
    let debounce;
    q.addEventListener("input", () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { state.q = q.value.trim(); state.page = 1; load(); }, 220);
    });

    document.getElementById("per-page").value = String(state.per_page);
    document.getElementById("per-page").addEventListener("change", (e) => {
      state.per_page = parseInt(e.target.value, 10); state.page = 1; load();
    });

    document.getElementById("clear-filters").addEventListener("click", () => {
      for (const k of ["q","author","subject","language","condition","century","year_from","year_to","has_commentary"]) state[k] = "";
      state.page = 1;
      document.querySelectorAll("aside.filters select").forEach(s => s.value = "");
      document.querySelectorAll("aside.filters input").forEach(i => {
        if (i.type === "checkbox") i.checked = false; else i.value = "";
      });
      document.getElementById("q").value = "";
      load();
    });
  }

  function bindSort() {
    document.querySelectorAll("#ms-table thead th").forEach(th => {
      const s = th.getAttribute("data-sort");
      if (!s) return;
      th.addEventListener("click", () => {
        if (state.sort === s) state.order = state.order === "asc" ? "desc" : "asc";
        else { state.sort = s; state.order = "asc"; }
        state.page = 1;
        load();
      });
    });
  }

  function bindColumns() {
    const dd = document.getElementById("cols-dd");
    document.getElementById("cols-btn").addEventListener("click", (e) => {
      e.stopPropagation(); dd.classList.toggle("open");
    });
    document.addEventListener("click", (e) => { if (!dd.contains(e.target)) dd.classList.remove("open"); });

    const saved = JSON.parse(localStorage.getItem("ldii:cols") || "null");
    const boxes = dd.querySelectorAll("input[type=checkbox]");
    boxes.forEach(cb => {
      const col = cb.getAttribute("data-col");
      if (saved && typeof saved[col] === "boolean" && !cb.disabled) cb.checked = saved[col];
      cb.addEventListener("change", () => {
        applyColumnVisibility();
        const map = {};
        boxes.forEach(b => map[b.getAttribute("data-col")] = b.checked);
        localStorage.setItem("ldii:cols", JSON.stringify(map));
      });
    });
    applyColumnVisibility();
  }

  function applyColumnVisibility() {
    document.querySelectorAll("#cols-dd input[type=checkbox]").forEach(cb => {
      const col = cb.getAttribute("data-col");
      const hide = !cb.checked;
      document.querySelectorAll(`#ms-table [data-col="${col}"]`).forEach(el => {
        el.classList.toggle("hidden-col", hide);
      });
    });
  }

  // ---- init ----
  readURL();
  bindFilters();
  bindSort();
  bindColumns();
  load();
})();
