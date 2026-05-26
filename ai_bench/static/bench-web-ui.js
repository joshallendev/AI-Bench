// ── bench-web-ui.js ──────────────────────────────────────────────
// API-wired AI-Bench dashboard controller
// Loaded by bench-web.html via <script src="bench-web-ui.js">

(async function () {
  "use strict";

  // ── API layer ───────────────────────────────────────────────────

  const api = {
    async health() {
      const r = await fetch("/api/health");
      if (!r.ok) throw new Error("health check failed");
      return r.json();
    },

    async getConfig() {
      const r = await fetch("/api/config");
      if (!r.ok) throw new Error("fetch config failed");
      return r.json();
    },

    async saveConfig(config) {
      const r = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      if (!r.ok) throw new Error("save config failed");
      return r.json();
    },

    async detect() {
      const r = await fetch("/api/detect");
      if (!r.ok) throw new Error("detect failed");
      return r.json();
    },

    async installedModels() {
      const r = await fetch("/api/models/installed");
      if (!r.ok) throw new Error("installed models failed");
      return r.json();
    },

    async searchModels(backend, query) {
      const params = new URLSearchParams({ backend, q: query });
      const r = await fetch(`/api/models/search?${params.toString()}`);
      if (!r.ok) throw new Error("model search failed: " + (await r.text()));
      return r.json();
    },

    async preflightModels(request) {
      const r = await fetch("/api/models/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      if (!r.ok) throw new Error("model preflight failed: " + (await r.text()));
      return r.json();
    },

    async listRuns() {
      const r = await fetch("/api/runs");
      if (!r.ok) throw new Error("list runs failed");
      return r.json();
    },

    async getRun(runId) {
      const r = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
      if (!r.ok) throw new Error("get run failed");
      return r.json();
    },

    async getResults(runId) {
      const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/results`);
      if (!r.ok) throw new Error("get results failed");
      return r.json();
    },

    async getRawOutput(runId, index) {
      const params = new URLSearchParams({ index: String(index) });
      const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/raw-output?${params.toString()}`);
      if (!r.ok) throw new Error("get raw output failed");
      return r.json();
    },

    async getRunConfig(runId) {
      const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/config`);
      if (!r.ok) throw new Error("get run config failed: " + (await r.text()));
      return r.json();
    },

    async startRun(request) {
      const r = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      if (!r.ok) throw new Error("start run failed: " + (await r.text()));
      return r.json();
    },

    async stopRun() {
      const r = await fetch("/api/runs/current/stop", { method: "POST" });
      if (!r.ok) throw new Error("stop run failed");
      return r.json();
    },

    async deleteRun(runId) {
      const r = await fetch(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },

    connectEvents(onEvent) {
      let closed = false;
      let retries = 0;
      let es = null;
      const maxRetries = 10;
      const baseDelayMs = 500;

      function connect() {
        es = new EventSource("/api/events");
        const handle = function (ev) {
          try {
            retries = 0;
            onEvent(JSON.parse(ev.data));
          } catch (_) {}
        };
        es.onmessage = handle;
        [
          "preflight",
          "plan",
          "backend_start",
          "backend_stop",
          "combo_start",
          "iteration_start",
          "iteration_complete",
          "results",
          "cleanup",
          "fatal_error",
          "status",
          "log",
        ].forEach((name) => es.addEventListener(name, handle));
        es.onerror = function () {
          es.close();
          if (closed || retries >= maxRetries) return;
          const delay = Math.min(baseDelayMs * Math.pow(2, retries), 30000);
          retries += 1;
          setTimeout(connect, delay);
        };
      }

      connect();
      return () => {
        closed = true;
        if (es) es.close();
      };
    },
  };

  // Make api accessible for debug / modal
  window.benchApi = api;

  // ── App state ──────────────────────────────────────────────────

  let appState = {
    runs: [],
    currentRun: null,
    detection: null,
    config: null,
    liveSseDisconnect: null,
    selectedRunId: null,
    matrixMetric: "toks",
    hlAgent: null,
    dark: false,
    compareMode: false,
    liveTests: [],
    liveTotal: 0,
    liveDone: 0,
    liveName: "",
  };

  // ── Helpers ────────────────────────────────────────────────────

  function avg(arr) {
    return arr.reduce((s, v) => s + v, 0) / arr.length;
  }

  function std(arr) {
    const m = avg(arr);
    return Math.sqrt(arr.reduce((s, v) => s + Math.pow(v - m, 2), 0) / arr.length);
  }

  function timeAgo(ts) {
    if (!ts) return "";
    const d = parseTimestamp(ts);
    if (!d) return String(ts);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 5) return "just now";
    if (diff < 60) return Math.floor(diff) + "s ago";
    if (diff < 3600) {
      const minutes = Math.floor(diff / 60);
      return minutes + " " + (minutes === 1 ? "min" : "mins") + " ago";
    }
    if (diff < 86400) {
      const hours = Math.floor(diff / 3600);
      return hours + " " + (hours === 1 ? "hr" : "hrs") + " ago";
    }
    const days = Math.floor(diff / 86400);
    return days + " " + (days === 1 ? "day" : "days") + " ago";
  }

  function parseTimestamp(ts) {
    if (ts instanceof Date && !isNaN(ts.getTime())) return ts;
    const value = String(ts);
    const compact = value.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/);
    if (compact) {
      const [, y, mo, d, h, mi, s] = compact;
      const parsed = new Date(
        Number(y),
        Number(mo) - 1,
        Number(d),
        Number(h),
        Number(mi),
        Number(s)
      );
      return isNaN(parsed.getTime()) ? null : parsed;
    }
    const parsed = new Date(value);
    return isNaN(parsed.getTime()) ? null : parsed;
  }

  function showApiError(msg) {
    console.error("[bench]", msg);
    // Non-blocking: just console log errors. Repeated errors will be visible in console.
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }

  function jsString(value) {
    return JSON.stringify(String(value ?? ""));
  }

  function cssString(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(String(value ?? ""));
    }
    return String(value ?? "").replace(/["\\]/g, "\\$&");
  }

  function handlerAttr(code) {
    return escapeAttr(code);
  }

  // ── Dark mode ──────────────────────────────────────────────────

  function toggleDark() {
    appState.dark = !appState.dark;
    document.body.classList.toggle("dark", appState.dark);
    const btn = document.getElementById("btn-dark");
    if (btn) btn.textContent = appState.dark ? "☽" : "☀";
  }
  window.toggleDark = toggleDark;

  // ── Navigation ─────────────────────────────────────────────────

  let currentView = "dashboard";
  let configureReady = false;

  function switchView(name) {
    currentView = name;
    document.querySelectorAll(".nav-item").forEach((el) =>
      el.classList.toggle("active", el.dataset.view === name)
    );
    document.querySelectorAll(".view").forEach((el) =>
      el.classList.remove("active")
    );
    const viewEl = document.getElementById("view-" + name);
    if (viewEl) viewEl.classList.add("active");

    const compareMode = name === "compare";
    appState.compareMode = compareMode;
    const sidebar = document.getElementById("sidebar");
    if (sidebar) sidebar.classList.toggle("compare-mode", compareMode);
    const btnNew = document.getElementById("btn-new");
    if (btnNew) btnNew.style.display = compareMode ? "none" : "";
    const cta = document.getElementById("btn-compare-cta");
    if (cta) cta.classList.toggle("visible", compareMode);
    if (!compareMode) {
      document.querySelectorAll(".run-check").forEach((c) => (c.checked = false));
      updateCompareCta();
    }

    if (name === "configure" && !configureReady) {
      configureReady = true;
      renderHarnesses();
    }
    if (name === "live") {
      renderLiveView();
    }
  }
  window.switchView = switchView;

  // ── Run history (API-driven) ───────────────────────────────────

  async function refreshRuns() {
    try {
      const runs = await api.listRuns();
      appState.runs = Array.isArray(runs) ? runs : [];
      // Check for active live run
      const running = appState.runs.find(
        (r) => r.status === "running"
      );
      appState.currentRun = running || null;
      if (appState.currentRun) {
        updateLiveFromRun(appState.currentRun);
        setLiveState();
      }
      renderRunHistory();
      if (!appState.currentRun) {
        const topbar = document.getElementById("topbar");
        const wasLive = topbar && topbar.classList.contains("is-live");
        setIdleState({ clearLive: wasLive });
        const selected = appState.runs.find((r) => r.run_id === appState.selectedRunId);
        const fallback = wasLive && appState.selectedRunId && (!selected || selected.status !== "completed")
          ? appState.runs.find((r) => r.status === "completed")
          : selected;
        if (fallback && (!selected || wasLive)) {
          if (fallback.run_id !== appState.selectedRunId || !selected) {
            appState.selectedRunId = fallback.run_id;
          }
          await loadRun(fallback.run_id);
        } else if (!appState.selectedRunId) {
          clearDashboard();
        }
      }
    } catch (e) {
      showApiError("refreshRuns: " + e.message);
    }
  }

  function renderRunHistory() {
    const history = document.querySelector(".history");
    if (!history) return;

    const anchor = history.querySelector(".history-head") || history.querySelector(".history-label");
    // Remove existing run rows
    history.querySelectorAll(".run-row, .run-empty").forEach((r) => r.remove());
    updateClearHistoryButton();

    if (appState.runs.length === 0) {
      const empty = document.createElement("div");
      empty.className = "run-empty";
      empty.style.cssText =
        "padding:16px 8px;text-align:center;font-size:12px;color:var(--ink-3)";
      empty.textContent = "No runs yet";
      if (anchor) anchor.after(empty);
      return;
    }

    let insertAfter = anchor;
    appState.runs.forEach((run) => {
      const row = document.createElement("div");
      row.className = "run-row" + (appState.selectedRunId === run.run_id ? " active" : "");
      row.dataset.runId = run.run_id;
      row.title = run.name || "";
      row.onclick = () => handleRunRowClick(run.run_id, row);

      const dotClass =
        run.status === "running"
          ? "live"
          : run.status === "failed"
          ? "failed"
          : run.status === "cancelled"
          ? "cancelled"
          : "done";

      const age = run.status === "running" ? "live" : timeAgo(run.timestamp);

      row.innerHTML = `
        <input type="checkbox" class="run-check" onchange="window.updateCompareCta()" onclick="event.stopPropagation()">
        <div class="dot ${escapeAttr(dotClass)}"></div>
        <span class="run-row-name">${escapeHtml(run.name || run.run_id)}</span>
        <span class="run-row-age">${escapeHtml(age)}</span>
        <button class="run-del" title="Delete" onclick="window.deleteRun(this,event)">×</button>`;

      insertAfter.after(row);
      insertAfter = row;
    });
  }

  function updateClearHistoryButton() {
    const btn = document.getElementById("btn-clear-history");
    if (!btn) return;
    const deletableCount = appState.runs.filter((run) => run.status !== "running").length;
    btn.disabled = deletableCount === 0;
    btn.title = deletableCount
      ? `Delete ${deletableCount} completed run${deletableCount === 1 ? "" : "s"}`
      : "No completed runs to delete";
  }

  function handleRunRowClick(runId, row) {
    if (currentView === "compare") {
      const checkbox = row && row.querySelector(".run-check");
      if (checkbox) {
        checkbox.checked = !checkbox.checked;
        updateCompareCta();
      }
      return;
    }
    loadRun(runId);
  }

  async function loadRun(runId) {
    appState.selectedRunId = runId;
    renderRunHistory(); // update active highlight

    if (currentView !== "dashboard") {
      switchView("dashboard");
    }

    try {
      const payload = await api.getResults(runId);
      renderDashboard(payload);
      updateTopbarFromRun(appState.runs.find((r) => r.run_id === runId));
    } catch (e) {
      showApiError("loadRun: " + e.message);
    }
  }
  window.loadRun = loadRun;

  function selectRun(row) {
    if (currentView === "compare") return;
    document.querySelectorAll(".run-row").forEach((r) => r.classList.remove("active"));
    row.classList.add("active");
  }
  window.selectRun = selectRun;

  async function deleteRun(btn, e) {
    e.stopPropagation();
    const row = btn.closest(".run-row");
    const runId = row && row.dataset.runId;
    if (!runId) return;
    if (typeof confirm === "function" && !confirm(`Delete run ${runId}? This cannot be undone.`)) {
      return;
    }
    try {
      await api.deleteRun(runId);
      row.remove();
      updateCompareCta();
      if (appState.selectedRunId === runId) {
        appState.selectedRunId = null;
        appState.currentRun = null;
        clearDashboard();
        await refreshRuns();
      }
    } catch (err) {
      alert("Failed to delete run: " + err.message);
    }
  }
  window.deleteRun = deleteRun;

  async function clearRunHistory() {
    const deletableRuns = appState.runs.filter((run) => run.status !== "running");
    if (deletableRuns.length === 0) return;

    const skipped = appState.runs.length - deletableRuns.length;
    const message =
      `Delete ${deletableRuns.length} completed run${deletableRuns.length === 1 ? "" : "s"}?` +
      (skipped ? " Active runs will stay in history." : "") +
      " This cannot be undone.";
    if (typeof confirm === "function" && !confirm(message)) return;

    const btn = document.getElementById("btn-clear-history");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Clearing...";
    }

    const failures = [];
    for (const run of deletableRuns) {
      try {
        await api.deleteRun(run.run_id);
      } catch (err) {
        failures.push(run.run_id);
      }
    }

    if (deletableRuns.some((run) => run.run_id === appState.selectedRunId)) {
      appState.selectedRunId = null;
      appState.currentRun = null;
      clearDashboard();
    }

    await refreshRuns();

    if (btn) btn.textContent = "Clear all";
    if (failures.length) {
      alert(`Failed to delete ${failures.length} run${failures.length === 1 ? "" : "s"}.`);
    }
  }
  window.clearRunHistory = clearRunHistory;

  function clearLiveProgress() {
    appState.currentRun = null;
    appState.liveTests = [];
    appState.livePlan = [];
    appState.liveDone = 0;
    appState.liveTotal = 0;
    liveStep = 0;
    liveTotalSteps = 0;
    const fill = document.getElementById("progress-fill");
    const count = document.getElementById("progress-count");
    const agent = document.getElementById("progress-agent");
    if (fill) fill.style.width = "0%";
    if (count) count.textContent = "0 / 0";
    if (agent) agent.textContent = "Waiting";
  }

  function setIdleState(options) {
    const opts = options || {};
    if (opts.clearLive) {
      clearLiveProgress();
    }
    document.getElementById("topbar").classList.remove("is-live");
    const statStrip = document.getElementById("stat-strip");
    if (statStrip) statStrip.style.display = "";
    updateLiveButton(false);
    updateLiveStopControls(false);
    renderLiveView();
  }

  function markLiveStopped(result) {
    const title = document.getElementById("topbar-title");
    const meta = document.getElementById("topbar-meta");
    const name = appState.liveName ||
      (appState.currentRun && appState.currentRun.name) ||
      (result && result.run_id ? "Run " + result.run_id : "Benchmark run");
    appState.currentRun = null;
    setIdleState({ clearLive: true });
    if (title) title.textContent = name + " stopped";
    if (meta) {
      const status = result && result.status ? result.status : "cancelled";
      meta.textContent = status + " just now";
    }
  }

  function updateTopbarFromRun(run) {
    if (!run) return;
    const title = document.getElementById("topbar-title");
    const meta = document.getElementById("topbar-meta");
    if (title) {
      title.textContent = run.name || "Run " + run.run_id;
    }
    if (meta) {
      const parts = [];
      if (run.iterations) parts.push(run.iterations + " iterations");
      if (run.warmup != null) parts.push(run.warmup + " warmup");
      if (run.combo_count) parts.push(run.combo_count + " runs complete");
      parts.push("finished " + timeAgo(run.timestamp));
      meta.textContent = parts.join(" \u00b7 ");
    }
  }

  function setLiveState(status) {
    const topbar = document.getElementById("topbar");
    if (topbar) topbar.classList.add("is-live");
    const statStrip = document.getElementById("stat-strip");
    if (statStrip) statStrip.style.display = "none";
    updateLiveButton(true);
    updateLiveStopControls(true);
    renderLiveView();
  }

  function updateLiveButton(isLive) {
    const btn = document.getElementById("btn-new");
    if (!btn) return;
    btn.classList.toggle("stop", !!isLive);
    btn.textContent = isLive ? "Stop" : "+ New Benchmark Run";
    btn.onclick = isLive ? () => window.stopLive() : openNewRunModal;
  }

  function isLiveRunActive() {
    const topbar = document.getElementById("topbar");
    return !!(
      (appState.currentRun && appState.currentRun.status === "running") ||
      (topbar && topbar.classList.contains("is-live"))
    );
  }

  function updateLiveStopControls(isLive = isLiveRunActive()) {
    document.querySelectorAll(".live-stop-action").forEach((btn) => {
      btn.disabled = !isLive;
      btn.textContent = isLive ? "Stop run" : "Stopped";
    });
  }

  // ── Dashboard rendering ────────────────────────────────────────

  function renderDashboard(payload) {
    if (!payload) return;
    const { matrix, leaderboard } = payload;
    appState._matrixData = matrix || [];
    appState._leaderboardData = leaderboard || [];
    renderStats(payload.summary);
    renderMatrix(appState._matrixData, metric);
    renderLeaderboard(appState._leaderboardData);
    renderPrompt(payload.prompt || "");
    renderRawOutputs(payload.raw_outputs || []);
  }

  function clearDashboard() {
    appState._matrixData = [];
    appState._leaderboardData = [];
    const statStrip = document.getElementById("stat-strip");
    const matrixScroll = document.querySelector(".matrix-scroll");
    const tbody = document.getElementById("leaderboard-body");
    const promptBody = document.querySelector(".prompt-body");
    const promptFoot = document.querySelector(".prompt-foot");
    const rawSelect = document.getElementById("raw-output-select");
    const rawMeta = document.getElementById("raw-output-meta");
    const rawBody = document.getElementById("raw-output-body");
    if (statStrip) statStrip.innerHTML = "";
    if (matrixScroll) matrixScroll.innerHTML = "";
    if (tbody) tbody.innerHTML = "";
    if (promptBody) promptBody.textContent = "";
    if (promptFoot) promptFoot.innerHTML = "";
    if (rawSelect) rawSelect.innerHTML = "";
    if (rawMeta) rawMeta.textContent = "";
    if (rawBody) rawBody.textContent = "Select a completed run to view raw output.";
    appState.liveLog = [];
    renderLiveLog();
  }

  function renderStats(summary) {
    const statStrip = document.getElementById("stat-strip");
    if (!statStrip || !summary) return;

    const fastest = summary.fastest_wall_s;

    // We need peak throughput and TTFT from matrix if not in summary
    statStrip.innerHTML = `
      <div class="stat-item">
        <div class="stat-num sage">${fastest != null ? fastest.toFixed(1) : '\u2014'}<span class="unit">s</span></div>
        <div class="stat-label">fastest wall time</div>
      </div>
      <div class="stat-item">
        <div class="stat-num">${summary.peak_throughput != null ? summary.peak_throughput.toFixed(1) : '\u2014'}<span class="unit"> tok/s</span></div>
        <div class="stat-label">peak throughput</div>
      </div>
      <div class="stat-item">
        <div class="stat-num">${summary.best_ttft != null ? summary.best_ttft.toFixed(2) : '\u2014'}<span class="unit">s</span></div>
        <div class="stat-label">best TTFT</div>
      </div>
      <div class="stat-item">
        <div class="stat-num">${summary.combo_count ?? '\u2014'}</div>
        <div class="stat-label">runs complete</div>
      </div>
    `;
  }

  function renderMatrix(payload, metric) {
    const matrixScroll = document.querySelector(".matrix-scroll");
    if (!matrixScroll) return;
    if (!payload || payload.length === 0) {
      matrixScroll.innerHTML = "";
      return;
    }

    // Extract models, agents from data
    const models = [...new Set(payload.map((m) => m.model))];
    const agents = [...new Set(payload.map((m) => m.agent))];

    // Determine tier classes
    const values = payload.map((p) =>
      metric === "toks" ? p.throughput_tok_s || 0 : -(p.wall_s || 0)
    );
    const sorted = [...values].sort((a, b) => b - a);
    const tiers = computeTiers(sorted);

    matrixScroll.innerHTML = `
      <div class="matrix-grid" style="grid-template-columns: minmax(110px, auto) repeat(${agents.length}, 1fr)">
        <div class="matrix-col-head"></div>
        ${agents.map((a) => `<div class="matrix-col-head${appState.hlAgent === a ? ' hl' : ''}" data-agent="${escapeAttr(a)}">${escapeHtml(a)}</div>`).join("")}
        ${models.map((model) => {
          const label = model;
          let rowHtml = `<div class="matrix-row-label">${escapeHtml(label)}</div>`;
          agents.forEach((agent) => {
            const cell = payload.find(
              (p) => p.model === model && p.agent === agent
            );
            if (!cell) {
              rowHtml += `<div class="cell pending"><div class="cell-num">\u2014</div><div class="cell-unit">na</div><div class="cell-sub"></div></div>`;
              return;
            }
            const val = metric === "toks" ? cell.throughput_tok_s : cell.wall_s;
            const unit = metric === "toks" ? "tok/s" : "s wall";
            const sub =
              metric === "toks"
                ? cell.wall_s != null ? cell.wall_s.toFixed(1) + "s wall" : ""
                : cell.throughput_tok_s != null
                ? cell.throughput_tok_s.toFixed(1) + " tok/s"
                : "";
            const tier = val != null ? tiers[val] || "t3" : "t3";
            const bestIdx = sorted.indexOf(metric === "toks" ? val : -val);
            const isBest = bestIdx === 0;
            rowHtml += `<div class="cell ${escapeAttr(tier)}${isBest ? " best" : ""}" data-model="${escapeAttr(model)}" data-agent="${escapeAttr(agent)}" onclick="window.cellClick(this)">
              <div class="cell-num">${val != null ? val.toFixed(1) : '\u2014'}</div>
              <div class="cell-unit">${escapeHtml(unit)}</div>
              <div class="cell-sub">${escapeHtml(sub)}</div>
            </div>`;
          });
          return rowHtml;
        }).join("")}
      </div>`;
  }

  function computeTiers(sorted) {
    if (sorted.length === 0) return {};
    const n = [...sorted];
    const tiers = {};
    n.forEach((v, i) => {
      const count = n.length;
      let tier;
      if (i < count * 0.2) tier = "t1";
      else if (i < count * 0.4) tier = "t2";
      else if (i < count * 0.6) tier = "t3";
      else if (i < count * 0.8) tier = "t4";
      else tier = "t5";
      // Map the original value back to tier (handle inverted for wall time)
      tiers[v] = tier;
    });
    return tiers;
  }

  function renderLeaderboard(payload) {
    const tbody = document.getElementById("leaderboard-body");
    if (!tbody) return;
    if (!payload.length) {
      tbody.innerHTML = "";
      return;
    }

    const sorted = [...payload].sort((a, b) => {
      if (sortCol === "agent") {
        const byAgent = String(a.agent || "").localeCompare(String(b.agent || ""));
        if (byAgent !== 0) return sortDir === "asc" ? byAgent : -byAgent;
        return String(a.model || "").localeCompare(String(b.model || ""));
      }
      const highIsGood = sortCol === "toks";
      const fallback = highIsGood ? 0 : Number.POSITIVE_INFINITY;
      const valueFor = (row) =>
        sortCol === "wall"
          ? row.wall_s ?? fallback
          : sortCol === "ttft"
          ? row.ttft_s ?? fallback
          : row.throughput_tok_s ?? fallback;
      const d = valueFor(a) - valueFor(b);
      return sortDir === "asc" ? d : -d;
    });

    tbody.innerHTML = sorted
      .map(
        (row, i) => `
      <tr data-agent="${escapeAttr(row.agent)}" onclick="${handlerAttr(`window.highlightAgent(${jsString(row.agent)})`)}"${
        appState.hlAgent === row.agent ? ' class="hl"' : ""
      }>
        <td><span class="rank${i === 0 ? " first" : ""}">${i + 1}</span></td>
        <td><span class="agent-name">${escapeHtml(row.agent)}</span></td>
        <td class="num r">${row.wall_s != null ? row.wall_s.toFixed(1) + "s" : '\u2014'}</td>
        <td><div class="bar-cell"><div class="bar-track"></div><span class="bar-val">${row.throughput_tok_s != null ? row.throughput_tok_s.toFixed(1) : '\u2014'}</span></div></td>
        <td class="num r">${row.ttft_s != null ? row.ttft_s.toFixed(2) + "s" : '\u2014'}</td>
      </tr>`
      )
      .join("");
  }

  function renderPrompt(text) {
    const promptBody = document.querySelector(".prompt-body");
    const promptFoot = document.querySelector(".prompt-foot");
    if (promptBody) {
      promptBody.textContent = text || "No prompt recorded.";
    }
    if (promptFoot) {
      promptFoot.innerHTML =
        text != null
          ? `<span>${(text || "").length} chars</span><span></span>`
          : "";
    }
  }

  function rawOutputLabel(item, index) {
    const iter = item.iteration != null ? `iter ${item.iteration}` : `output ${index + 1}`;
    return [item.label || item.model || "run", iter].filter(Boolean).join(" · ");
  }

  function renderRawOutputs(outputs) {
    appState._rawOutputs = outputs || [];
    const select = document.getElementById("raw-output-select");
    if (select) {
      select.innerHTML = appState._rawOutputs.length
        ? appState._rawOutputs
            .map((item, i) => `<option value="${i}">${escapeHtml(rawOutputLabel(item, i))}</option>`)
            .join("")
        : '<option value="">No raw output files found</option>';
      select.disabled = appState._rawOutputs.length === 0;
    }
    if (appState._rawOutputs.length) {
      selectRawOutput("0");
    } else {
      selectRawOutput("");
    }
  }

  async function selectRawOutput(value) {
    const meta = document.getElementById("raw-output-meta");
    const body = document.getElementById("raw-output-body");
    const index = Number.parseInt(value, 10);
    const item = Number.isFinite(index) ? (appState._rawOutputs || [])[index] : null;
    if (!item) {
      if (meta) meta.textContent = "";
      if (body) body.textContent = "No raw output files were recorded for this run.";
      return;
    }
    if (!appState.selectedRunId) {
      if (meta) meta.textContent = "";
      if (body) body.textContent = "Select a completed run to view raw output.";
      return;
    }
    if (meta) meta.textContent = "Loading...";
    if (body) body.textContent = "";
    try {
      const payload = await api.getRawOutput(appState.selectedRunId, item.index ?? index);
      const text = payload.text || "";
      if (meta) {
        meta.textContent =
          `${text.length.toLocaleString()} chars` + (payload.truncated ? " · truncated" : "");
      }
      if (body) body.textContent = text || "(empty output)";
    } catch (e) {
      if (meta) meta.textContent = "";
      if (body) body.textContent = "Failed to load raw output: " + e.message;
    }
  }
  window.selectRawOutput = selectRawOutput;

  // ── Matrix metric toggle ───────────────────────────────────────

  let metric = "toks";

  function switchMetric(m) {
    metric = m;
    document.querySelectorAll(".seg-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset.metric === m)
    );
    const label = document.getElementById("matrix-label");
    if (label) {
      label.textContent =
        m === "toks"
          ? "Eval throughput \u00b7 raw backend generation speed"
          : "Wall time \u00b7 total harness round-trip per run";
    }
    // Re-render matrix with current data if available
    if (appState._matrixData) {
      renderMatrix(appState._matrixData, m);
    }
  }
  window.switchMetric = switchMetric;

  // ── Leaderboard sort ───────────────────────────────────────────

  let sortCol = "toks",
    sortDir = "desc";

  function sortBy(col) {
    if (sortCol === col) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortDir = col === "toks" ? "desc" : "asc";
    }
    sortCol = col;
    document.querySelectorAll("th.sortable").forEach((th) => {
      th.classList.remove("sort-asc", "sort-desc");
      th.setAttribute("aria-sort", "none");
      if (th.dataset.col === col) {
        th.classList.add("sort-" + sortDir);
        th.setAttribute("aria-sort", sortDir === "asc" ? "ascending" : "descending");
      }
    });
    renderLeaderboard(appState._leaderboardData || []);
  }
  window.sortBy = sortBy;

  function highlightAgent(name) {
    appState.hlAgent = appState.hlAgent === name ? null : name;
    document.querySelectorAll(".cell").forEach((c) => c.classList.remove("hl"));
    document.querySelectorAll(".matrix-col-head").forEach((h) =>
      h.classList.remove("hl")
    );
    if (appState.hlAgent) {
      document
        .querySelectorAll(`.cell[data-agent="${cssString(appState.hlAgent)}"]`)
        .forEach((c) => c.classList.add("hl"));
      document
        .querySelectorAll(
          `.matrix-col-head[data-agent="${cssString(appState.hlAgent)}"]`
        )
        .forEach((h) => h.classList.add("hl"));
    }
    // Re-render leaderboard with highlight
    renderLeaderboard(appState._leaderboardData || []);
  }
  window.highlightAgent = highlightAgent;

  // ── Cell popover ───────────────────────────────────────────────

  const popover =
    typeof document !== "undefined" ? document.getElementById("cell-popover") : null;

  function cellClick(cell) {
    if (!popover) return;
    if (popover.classList.contains("visible") && popover._src === cell) {
      hidePopover();
      return;
    }
    const model = cell.dataset.model;
    const agent = cell.dataset.agent;

    // Look for per-iteration data in the run results
    const comboData = appState._comboIters
      ? appState._comboIters[model + "-" + agent]
      : null;

    let html = `<div class="popover-header">${escapeHtml(model)} \u00d7 ${escapeHtml(agent)}</div>`;

    if (comboData && comboData.iters && comboData.iters.length > 0) {
      html += `<div class="popover-iter">`;
      comboData.iters.forEach((it, i) => {
        html += `<span class="popover-iter-label">iter ${i + 1}</span>
              <span class="popover-val">${(it.tok_s || 0).toFixed(1)} tok/s</span>
              <span class="popover-val">${(it.wall_s || 0).toFixed(1)}s</span>`;
      });
      const avgT = avg(comboData.iters.map((i) => i.tok_s || 0));
      const avgW = avg(comboData.iters.map((i) => i.wall_s || 0));
      const stdV = std(comboData.iters.map((i) => i.tok_s || 0));
      html += `</div><div class="popover-divider"></div>
        <div class="popover-avg">
          <span class="popover-avg-label">avg</span>
          <span class="popover-avg-val">${avgT.toFixed(1)} \u00b1${stdV.toFixed(1)}</span>
          <span class="popover-avg-val">${avgW.toFixed(1)}s</span>
        </div>`;
    } else {
      // Show what we have in the cell
      const num = cell.querySelector(".cell-num");
      html += `<div class="popover-avg">
        <span class="popover-avg-label">value</span>
        <span class="popover-avg-val">${escapeHtml(num ? num.textContent : '\u2014')}</span>
        <span class="popover-avg-val">\u2014</span>
      </div>`;
    }

    popover.innerHTML = html;
    popover._src = cell;
    const r = cell.getBoundingClientRect();
    const pw = 200;
    let left = r.right + 8;
    if (left + pw > window.innerWidth - 8) left = r.left - pw - 8;
    let top = r.top;
    if (top + 140 > window.innerHeight - 8) top = window.innerHeight - 148;
    popover.style.left = left + "px";
    popover.style.top = top + "px";
    popover.classList.add("visible");
  }
  window.cellClick = cellClick;

  function hidePopover() {
    if (!popover) return;
    popover.classList.remove("visible");
    popover._src = null;
  }
  if (typeof document !== "undefined") {
    document.addEventListener("click", (e) => {
      if (
        !e.target.closest(".cell") &&
        !e.target.closest("#cell-popover")
      )
        hidePopover();
    });
  }

  // ── Compare ────────────────────────────────────────────────────

  function updateCompareCta() {
    const n = document.querySelectorAll(".run-check:checked").length;
    const btn = document.getElementById("btn-compare-cta");
    if (!btn) return;
    if (n === 0) btn.textContent = "Select runs to compare";
    else if (n === 1) btn.textContent = "Select one more\u2026";
    else btn.textContent = `Compare selected (${n})`;
    btn.classList.toggle("ready", n >= 2);
    btn.disabled = n < 2;
  }
  window.updateCompareCta = updateCompareCta;

  async function runCompare() {
    const checked = [...document.querySelectorAll(".run-check:checked")];
    if (checked.length < 2) return;

    const runIds = checked
      .map((c) => c.closest(".run-row"))
      .map((row) => row && row.dataset.runId)
      .filter(Boolean);

    const results = [];
    for (const runId of runIds) {
      const run = appState.runs.find((r) => r.run_id === runId);
      if (!run) continue;
      try {
        const payload = await api.getResults(run.run_id);
        results.push({
          name: run.name,
          meta: `${run.iterations || "?"} iter \u00b7 ${run.combo_count || "?"} runs`,
          payload,
        });
      } catch (e) {
        showApiError("runCompare failed for " + run.run_id + ": " + e.message);
      }
    }

    if (results.length >= 2) {
      renderCompare(results);
      document.getElementById("compare-empty").style.display = "none";
      document.getElementById("compare-results").style.display = "";
    }
  }
  window.runCompare = runCompare;

  function renderCompare(runs) {
    // Build comparison table from API payload
    // Gather all models/agents from all runs
    const allModels = new Set();
    const allAgents = new Set();
    const modelLabels = {};

    runs.forEach((run) => {
      (run.payload.matrix || []).forEach((m) => {
        allModels.add(m.model);
        allAgents.add(m.agent);
        modelLabels[m.model] = m.model;
      });
    });

    const models = [...allModels];
    const agents = [...allAgents];

    const best = {};
    const winCounts = runs.map(() => 0);
    models.forEach((m) =>
      agents.forEach((ag) => {
        const k = m + "-" + ag;
        const vals = runs.map((r) => {
          const cell = (r.payload.matrix || []).find(
            (c) => c.model === m && c.agent === ag
          );
          return cell != null ? (cell.throughput_tok_s ?? null) : null;
        });
        const nonNull = vals.filter((v) => v !== null);
        best[k] = nonNull.length > 0 ? Math.max(...nonNull) : null;
        vals.forEach((v, i) => {
          if (best[k] !== null && v !== null && v === best[k]) winCounts[i]++;
        });
      })
    );
    const maxWins = Math.max(...winCounts);

    let html = `
      <div class="compare-toolbar">
        <div class="compare-toolbar-left">
          <span class="compare-toolbar-title">Comparing ${runs.length} runs</span>
          <span class="compare-toolbar-sub">tok/s \u00b7 fastest per row highlighted</span>
        </div>
      </div>
      <div class="compare-table-wrap"><table class="ctable">
      <thead><tr>
        <th class="ch-combo">Model \u00d7 Agent</th>
        ${runs
          .map(
            (r, i) => {
              const winner = maxWins > 0 && winCounts[i] === maxWins;
              return `<th class="ch-run${winner ? " is-winner" : ""}">
            <span class="rh-name">${escapeHtml(r.name)}</span>
            <span class="rh-meta">${escapeHtml(r.meta)}</span>
            ${winner ? '<span class="rh-badge">winner</span>' : ""}
          </th>`;
            }
          )
          .join("")}
      </tr></thead>
      <tbody>`;

    models.forEach((m) => {
      html += `<tr class="tr-group"><td colspan="${
        runs.length + 1
      }">${escapeHtml(modelLabels[m] || m)}</td></tr>`;
      agents.forEach((ag) => {
        const k = m + "-" + ag;
        html += `<tr class="tr-data">
          <td class="td-agent">\u00d7 ${escapeHtml(ag)}</td>
          ${runs
            .map((r) => {
              const cell = (r.payload.matrix || []).find(
                (c) => c.model === m && c.agent === ag
              );
              const v = cell != null ? (cell.throughput_tok_s ?? null) : null;
              const isBest = best[k] !== null && v !== null && v === best[k];
              return `<td class="td-val${
                isBest ? " is-best" : ""
              }"><span class="v-num">${v !== null ? v.toFixed(1) : "—"}</span></td>`;
            })
            .join("")}
        </tr>`;
      });
    });

    html += `<tr class="tr-wins">
      <td class="td-wins-label">Wins</td>
      ${winCounts
        .map(
          (w) => `<td class="td-wins-val${maxWins > 0 && w === maxWins ? " is-most" : ""}">${w} / ${
            models.length * agents.length
          }</td>`
        )
        .join("")}
    </tr>`;

    html += `</tbody></table></div>`;
    document.getElementById("compare-results").innerHTML = html;
  }

  // ── Live run from SSE ──────────────────────────────────────────

  let liveTimer = null;
  let liveStep = 0;
  let liveTotalSteps = 0;

  function handleProgressEvent(event) {
    if (!event) return;
    const type = event.type;

    if (type === "log") {
      appendLiveLog(event);
      return;
    }

    if (type === "plan") {
      liveTotalSteps = event.total_runs || liveTotalSteps;
      appState.liveTotal = liveTotalSteps;
      appState.livePlan = expandLivePlan(event);
      document.getElementById("progress-count").textContent =
        "0 / " + liveTotalSteps;
      renderLiveView();
    }

    if (type === "iteration_start" || type === "iteration_complete") {
      upsertLiveTest(event, type === "iteration_complete" ? liveStatusFromCompleteEvent(event) : "running");
      liveStep = event.done || liveStep;
      appState.liveDone = liveStep;
      appState.liveTotal = liveTotalSteps;
      const pct = liveTotalSteps > 0
        ? Math.round((liveStep / liveTotalSteps) * 100)
        : 0;
      document.getElementById("progress-fill").style.width = pct + "%";
      document.getElementById("progress-count").textContent =
        liveStep + " / " + liveTotalSteps;
      if (event.label) {
        document.getElementById("progress-agent").textContent = event.label;
      }
      renderLiveView();
    }

    if (type === "results" || type === "results_written") {
      clearInterval(liveTimer);
      liveTimer = null;
      setTimeout(() => {
        refreshRuns();
        setIdleState({ clearLive: true });
      }, 1000);
    }

    if (type === "status" && event.status && event.status !== "running") {
      clearInterval(liveTimer);
      liveTimer = null;
      setTimeout(() => {
        refreshRuns();
        setIdleState({ clearLive: true });
      }, 500);
    }
  }
  window.handleProgressEvent = handleProgressEvent;

  function resetLiveRun(name, total) {
    appState.liveTests = [];
    appState.livePlan = [];
    appState.liveLog = [];
    appState.liveDone = 0;
    appState.liveTotal = total || 0;
    appState.liveName = name || "Benchmark run";
    liveStep = 0;
    liveTotalSteps = total || 0;
    renderLiveView();
  }

  function appendLiveLog(event) {
    appState.liveLog = appState.liveLog || [];
    appState.liveLog.push({
      timestamp: new Date().toLocaleTimeString([], {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
      stream: event.stream || "stdout",
      line: event.line || "",
    });
    if (appState.liveLog.length > 500) {
      appState.liveLog = appState.liveLog.slice(-500);
    }
    renderLiveLog();
  }

  function renderLiveLog() {
    const body = document.getElementById("live-log-body");
    const count = document.getElementById("live-log-count");
    if (!body) return;
    const rows = appState.liveLog || [];
    if (count) count.textContent = rows.length ? `${rows.length} lines` : "";
    body.innerHTML = rows.length
      ? rows
          .map((row) => `<div class="live-log-line ${escapeAttr(row.stream)}"><span class="live-log-time">${escapeHtml(row.timestamp || "")}</span><span class="live-log-stream">${escapeHtml(row.stream)}</span><span>${escapeHtml(row.line)}</span></div>`)
          .join("")
      : '<div class="live-log-empty">CLI output will stream here while the benchmark runs.</div>';
    body.scrollTop = body.scrollHeight;
  }

  function expandLivePlan(event) {
    const planned = Array.isArray(event.planned) ? event.planned : [];
    const warmup = Math.max(0, Number.parseInt(event.warmup, 10) || 0);
    const iterations = Math.max(0, Number.parseInt(event.iterations, 10) || 0);
    const rows = [];
    planned.forEach((combo) => {
      const label = combo.label || [combo.agent, combo.backend, combo.model_id].filter(Boolean).join("+");
      for (let i = 0; i < warmup; i += 1) {
        rows.push({
          key: [label, "warmup-" + i].join("::"),
          label,
          tag: "warmup-" + i,
          status: "pending",
        });
      }
      for (let i = 0; i < iterations; i += 1) {
        rows.push({
          key: [label, "iter-" + i].join("::"),
          label,
          tag: "iter-" + i,
          status: "pending",
        });
      }
    });
    return rows;
  }

  function updateLiveFromRun(run) {
    if (!run) return;
    appState.liveName = run.name || appState.liveName || "Benchmark run";
    appState.liveDone = run.progress_done || appState.liveDone || 0;
    appState.liveTotal = run.progress_total || appState.liveTotal || 0;
    liveStep = appState.liveDone;
    liveTotalSteps = appState.liveTotal;
    renderLiveView();
  }

  function upsertLiveTest(event, status) {
    const key = [event.label || "benchmark", event.tag || event.iteration || ""].join("::");
    let item = appState.liveTests.find((test) => test.key === key);
    if (!item) {
      item = {
        key,
        label: event.label || "benchmark",
        tag: event.tag || "",
        status: "pending",
        wall_s: null,
        rc: null,
        output_chars: null,
      };
      appState.liveTests.push(item);
    }
    if (status === "running") {
      appState.liveTests.forEach((test) => {
        if (test.key !== key && test.status === "running") {
          test.status = "unknown";
        }
      });
    }
    item.status = status;
    if (event.wall_s != null) item.wall_s = event.wall_s;
    if (event.rc != null) item.rc = event.rc;
    if (event.output_chars != null) item.output_chars = event.output_chars;
  }

  function liveStatusFromCompleteEvent(event) {
    if (event.rc != null && event.rc !== 0) return "failed";
    if (event.output_chars != null && event.output_chars === 0) return "empty";
    return "complete";
  }

  function renderLiveView() {
    const doneEl = document.getElementById("live-summary-done");
    if (!doneEl) return;
    const runningCount = appState.liveTests.filter((test) => test.status === "running").length;
    const explicitCompleteCount = appState.liveTests.filter((test) => test.status === "complete").length;
    const issueCount = appState.liveTests.filter((test) => test.status === "failed" || test.status === "empty").length;
    const completeCount = appState.liveTests.length
      ? explicitCompleteCount
      : appState.liveDone || 0;
    const total = Math.max(appState.liveTotal || 0, appState.liveTests.length);
    const pendingCount = Math.max(total - completeCount - runningCount, 0);

    doneEl.textContent = String(completeCount);
    document.getElementById("live-summary-issues").textContent = String(issueCount);
    document.getElementById("live-summary-running").textContent = String(runningCount);
    document.getElementById("live-summary-pending").textContent = String(pendingCount);

    const current = appState.liveTests.find((test) => test.status === "running");
    const title = document.getElementById("live-detail-title");
    const sub = document.getElementById("live-detail-sub");
    const viewSub = document.getElementById("live-view-sub");
    if (title) title.textContent = appState.liveName || "No active run";
    updateLiveStopControls();
    const subText = current
      ? "Running " + current.label + (current.tag ? " · " + current.tag : "")
      : total
      ? completeCount + " / " + total + " tests complete"
      : "Start a benchmark to see live progress here.";
    if (sub) sub.textContent = subText;
    if (viewSub) viewSub.textContent = subText;

    const list = document.getElementById("live-test-list");
    if (!list) return;
    renderLiveLog();
    const byKey = new Map((appState.livePlan || []).map((test) => [test.key, { ...test }]));
    appState.liveTests.forEach((test) => {
      byKey.set(test.key, { ...(byKey.get(test.key) || {}), ...test });
    });
    const rows = byKey.size ? [...byKey.values()] : [...appState.liveTests];
    while (rows.length < total) {
      rows.push({
        key: "pending-" + rows.length,
        label: "Queued test " + (rows.length + 1),
        tag: "",
        status: "pending",
      });
    }
    if (!rows.length) {
      list.innerHTML = '<div class="live-empty">No live run is active.</div>';
      return;
    }
    list.innerHTML = rows.map((test, index) => {
      const status = test.status || "pending";
      const meta = test.wall_s != null
        ? test.wall_s.toFixed(1) + "s"
        : test.tag || "";
      return `<div class="live-test-row ${escapeAttr(status)}">
        <span class="live-test-index">${index + 1}</span>
        <span class="live-test-status">${escapeHtml(liveStatusLabel(status))}</span>
        <span class="live-test-name">${escapeHtml(test.label)}</span>
        <span class="live-test-meta">${escapeHtml(meta)}</span>
      </div>`;
    }).join("");
  }

  function liveStatusLabel(status) {
    if (status === "complete") return "passed";
    if (status === "empty") return "empty";
    if (status === "failed") return "failed";
    if (status === "unknown") return "unknown";
    return status;
  }

  function stopLive(result) {
    if (liveTimer) {
      clearInterval(liveTimer);
      liveTimer = null;
    }
    markLiveStopped(result);
    refreshRuns();
  }
  window.stopLive = stopLive;

  // ── New Run Modal (API-driven) ─────────────────────────────────

  async function openNewRunModal() {
    const modelList = document.getElementById("run-modal").querySelector(
      ".modal-two-col > div:first-child"
    );

    if (modelList) {
      modelList.innerHTML = `<div class="modal-col-label">Models</div><div class="check-item disabled"><span class="check-item-label">Loading local models...</span></div>`;
    }
    document.getElementById("modal-overlay").classList.add("open");

    try {
      const catalog = await api.installedModels();
      appState.modelCatalog = catalog;
      renderModalModelPicker(catalog);
    } catch (e) {
      appState.modelCatalog = fallbackModelCatalog();
      renderModalModelPicker(appState.modelCatalog, e.message);
    }

    renderModalHarnessList();

    const promptArea = document.getElementById("modal-prompt");
    if (promptArea) {
      promptArea.value =
        (appState.config && appState.config.prompt) ||
        "Build a single-page website in plain HTML, CSS, and JavaScript with two buttons. The first button fetches a random joke from icanhazdadjoke.com and displays it. The second toggles dark mode. Output a single complete HTML file with inline <style> and <script> tags. No build tools, no frameworks.";
    }

    const iters = document.getElementById("mi-iters");
    const warmup = document.getElementById("mi-warmup");
    if (iters)
      iters.value = (appState.config && appState.config.iterations) || 3;
    if (warmup)
      warmup.value = (appState.config && appState.config.warmup) || 1;

  }
  window.openNewRunModal = openNewRunModal;

  function renderModalModelPicker(catalog, errorMessage) {
    const modelList = document.getElementById("run-modal").querySelector(
      ".modal-two-col > div:first-child"
    );
    if (!modelList) return;
    const groups = catalog && catalog.backends ? catalog.backends : {};
    const backendOrder = ["ollama", "lmstudio", "omlx"];
    const sections = backendOrder.map((backend) => {
      const items = groups[backend] || [];
      const resultId = "model-search-results-" + backend;
      return `<div class="model-picker-section">
        <div class="modal-col-label">${escapeHtml(backendLabel(backend))}</div>
        <div class="model-search-row">
          <input class="model-search-input" id="model-search-${escapeAttr(backend)}" placeholder="Search ${escapeAttr(backendLabel(backend))} models" onkeydown="${handlerAttr(`window.handleModelSearchKeydown(event, ${jsString(backend)})`)}">
          <button type="button" class="mini-btn" onclick="${handlerAttr(`window.searchModelBackend(${jsString(backend)})`)}">Search</button>
        </div>
        <div class="check-list model-check-list" id="model-list-${escapeAttr(backend)}">
          ${items.length
            ? items.map((item) => renderModelCheckItem(item, false)).join("")
            : `<div class="check-item disabled"><span class="check-item-label">No installed models found</span></div>`}
        </div>
        <div class="check-list model-search-results" id="${escapeAttr(resultId)}"></div>
      </div>`;
    });

    modelList.innerHTML =
      `<div class="modal-col-label">Models</div>` +
      (errorMessage
        ? `<div class="check-item disabled"><span class="check-item-label">${escapeHtml(errorMessage)}</span></div>`
        : "") +
      sections.join("");
  }

  function renderModelCheckItem(item, checked) {
    const entry = item && item.model_entry ? item.model_entry : {};
    const source = item.source || "installed";
    const badge = [
      item.backend,
      source === "remote" ? "download" : "local",
      item.size || "",
    ].filter(Boolean).join(" / ");
    return `<label class="check-item">
      <input type="checkbox" ${checked ? "checked" : ""} data-entry="${escapeAttr(JSON.stringify(entry))}" data-source="${escapeAttr(source)}" onchange="${handlerAttr("window.renderModalHarnessList()")}">
      <span class="check-item-label">${escapeHtml(item.label || item.id || entry.id || "model")}</span>
      <span class="check-item-badge ${source === "remote" ? "warn" : "ok"}">${escapeHtml(badge)}</span>
    </label>`;
  }

  function fallbackModelCatalog() {
    const installedBackends = new Set(
      ((appState.detection && appState.detection.backends) || []).map((b) =>
        typeof b === "string" ? b : b.id
      )
    );
    const backends = { ollama: [], lmstudio: [], omlx: [] };
    ((appState.config && appState.config.models) || []).forEach((model) => {
      ["ollama", "lmstudio", "omlx"].forEach((backend) => {
        if (!installedBackends.has(backend) || !model[backend]) return;
        const modelEntry = { id: model.id };
        modelEntry[backend] = model[backend];
        if (backend === "omlx" && model.omlx_hf) modelEntry.omlx_hf = model.omlx_hf;
        backends[backend].push({
          backend,
          id: model[backend],
          label: model.id,
          source: "installed",
          model_entry: modelEntry,
        });
      });
    });
    return { backends };
  }

  async function searchModelBackend(backend) {
    const input = document.getElementById("model-search-" + backend);
    const target = document.getElementById("model-search-results-" + backend);
    const query = input ? input.value.trim() : "";
    if (!target || !query) return;
    target.innerHTML = `<div class="check-item disabled"><span class="check-item-label">Searching...</span></div>`;
    try {
      const payload = await api.searchModels(backend, query);
      const results = payload.results || [];
      target.innerHTML = results.length
        ? results.map((item) => renderModelCheckItem(item, false)).join("")
        : `<div class="check-item disabled"><span class="check-item-label">No matching models found</span></div>`;
    } catch (e) {
      target.innerHTML = `<div class="check-item disabled"><span class="check-item-label">${escapeHtml(e.message)}</span></div>`;
    }
  }
  window.searchModelBackend = searchModelBackend;

  function handleModelSearchKeydown(event, backend) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    return searchModelBackend(backend);
  }
  window.handleModelSearchKeydown = handleModelSearchKeydown;
  window.renderModalHarnessList = renderModalHarnessList;

  function renderModalHarnessList() {
    const harnessList = document.getElementById("modal-harness-list");
    if (!harnessList) return;
    const agents = (appState.detection && appState.detection.agents) || [];
    const selectedBackends = selectedModalBackends();
    harnessList.innerHTML = agents
      .map((a) => {
        const supports = a.supports_backends || [];
        const compatible =
          !selectedBackends.length ||
          !supports.length ||
          supports.some((b) => selectedBackends.includes(b));
        const enabled = a.status === "installed" && compatible;
        return `<label class="check-item${enabled ? "" : " disabled"}">
          <input type="checkbox" data-id="${escapeAttr(a.id)}"${
            enabled ? ' checked' : " disabled"
          }>
          <span class="check-item-label">${escapeHtml(a.name || a.id)}</span>
          <span class="check-item-badge ${
            enabled ? "ok" : "off"
          }">${escapeHtml(
          enabled
            ? a.version || "installed"
            : a.status === "installed"
            ? "unsupported"
            : "not installed"
        )}</span>
        </label>`;
      })
      .join("");
  }

  function backendLabel(backend) {
    return {
      ollama: "Ollama",
      lmstudio: "LM Studio",
      omlx: "oMLX",
    }[backend] || backend;
  }

  function closeModal() {
    document.getElementById("modal-overlay").classList.remove("open");
  }
  window.closeModal = closeModal;

  function overlayClick(e) {
    if (e.target === document.getElementById("modal-overlay")) closeModal();
  }
  window.overlayClick = overlayClick;

  function collectRunRequestFromModal() {
    const selectedModels = selectedModalModelEntries();
    const modelEntries = mergeModelEntries(selectedModels.map((m) => m.entry));
    const models = modelEntries.map((entry) => entry.id).filter(Boolean);
    const backends = selectedModalBackends();
    const needsDownload = selectedModels.some((m) => m.source === "remote");

    const agents = [...document.querySelectorAll("#modal-harness-list input:checked")].map(
      (cb) => cb.dataset.id || cb.closest(".check-item").querySelector(".check-item-label").textContent.trim()
    );

    return {
      models,
      model_entries: modelEntries,
      agents,
      backends,
      iterations: parseInt(document.getElementById("mi-iters").value) || 3,
      warmup: parseInt(document.getElementById("mi-warmup").value) || 0,
      prompt: document.getElementById("modal-prompt").value || "",
      skip_install: !needsDownload,
    };
  }

  function selectedModalBackends() {
    const backends = new Set();
    selectedModalModelEntries().forEach(({ entry }) => {
      ["ollama", "lmstudio", "omlx"].forEach((backend) => {
        if (entry[backend]) backends.add(backend);
      });
    });
    return [...backends];
  }

  function selectedModalModelEntries() {
    return [
      ...document.querySelectorAll(
        "#run-modal .modal-two-col > div:first-child .check-list input:checked"
      ),
    ]
      .map((cb) => {
        try {
          return {
            entry: JSON.parse(cb.dataset.entry || "{}"),
            source: cb.dataset.source || "installed",
          };
        } catch (_) {
          return null;
        }
      })
      .filter((item) => item && item.entry && item.entry.id);
  }

  function mergeModelEntries(entries) {
    const byId = new Map();
    entries.forEach((entry) => {
      if (!entry || !entry.id) return;
      const existing = byId.get(entry.id) || { id: entry.id };
      Object.keys(entry).forEach((key) => {
        if (entry[key] != null && entry[key] !== "") existing[key] = entry[key];
      });
      byId.set(existing.id, existing);
    });
    return [...byId.values()];
  }

  async function startBenchmark() {
    const request = collectRunRequestFromModal();
    if (!request.models.length || !request.agents.length || !request.prompt.trim()) {
      alert("Select at least one model, one agent, and enter a prompt.");
      return;
    }

    try {
      const preflight = await api.preflightModels(request);
      if (!preflight.ok) {
        const messages = (preflight.issues || [])
          .filter((issue) => issue.level === "error")
          .map((issue) => issue.message)
          .join("\n");
        alert(messages || "The selected models are not ready to run.");
        return;
      }

      closeModal();

      const resp = await api.startRun(request);
      appState.currentRun = { run_id: resp.run_id, status: "running" };
      appState.selectedRunId = resp.run_id;
      const runName =
        request.models.length === 1
          ? request.models[0]
          : request.models.length + " models";
      const agentShort =
        request.agents.length === 1
          ? request.agents[0]
          : request.agents.length + " agents";
      const name = runName + " \u00d7 " + agentShort;
      const totalSteps = resp.planned_total ?? 0;
      resetLiveRun(name, totalSteps);

      // Update topbar
      document.getElementById("live-run-name").textContent = name;
      document.getElementById("topbar-title").textContent = name + " \u00b7 running";
      document.getElementById("topbar-meta").textContent =
        request.iterations +
        " iterations \u00b7 " +
        request.warmup +
        " warmup \u00b7 starting\u2026";

      setLiveState();
      switchView("live");

      // Add live run to history
      addRunToHistory(name, "running", resp.run_id);

      // Connect to SSE for live progress
      if (appState.liveSseDisconnect) {
        appState.liveSseDisconnect();
      }
      appState.liveSseDisconnect = api.connectEvents(handleProgressEvent);

      // Periodic run refresh to update history
      liveTimer = setInterval(refreshRuns, 5000);
    } catch (e) {
      showApiError("startBenchmark: " + e.message);
      alert("Failed to start benchmark: " + e.message);
    }
  }
  window.startBenchmark = startBenchmark;

  function addRunToHistory(name, status, runId) {
    const history = document.querySelector(".history");
    const anchor = history.querySelector(".history-head") || history.querySelector(".history-label");
    const row = document.createElement("div");
    row.className = "run-row active";
    row.dataset.runId = runId || "";
    row.title = name;
    row.onclick = () => handleRunRowClick(runId || "", row);

    const dotClass = status === "running" ? "live" : "done";

    row.innerHTML = `
    <input type="checkbox" class="run-check" onchange="window.updateCompareCta()" onclick="event.stopPropagation()">
    <div class="dot ${escapeAttr(dotClass)}"></div>
    <span class="run-row-name">${escapeHtml(name)}</span>
    <span class="run-row-age">${status === "running" ? "live" : "now"}</span>
    <button class="run-del" title="Delete" onclick="window.deleteRun(this,event)">\u00d7</button>`;

    document
      .querySelectorAll(".run-row.active")
      .forEach((r) => r.classList.remove("active"));
    if (anchor) anchor.after(row);
    updateClearHistoryButton();
  }

  function handleStopBenchmark() {
    api.stopRun().then((result) => {
      if (liveTimer) clearInterval(liveTimer);
      if (appState.liveSseDisconnect) appState.liveSseDisconnect();
      stopLive(result);
    }).catch((e) => {
      showApiError("handleStopBenchmark: " + e.message);
    });
  }
  window.handleStopBenchmark = handleStopBenchmark;

  // Keep stopLive handler for the topbar stop button
  function stopLiveWithApi() {
    return api.stopRun()
      .then((result) => {
        if (liveTimer) clearInterval(liveTimer);
        if (appState.liveSseDisconnect) appState.liveSseDisconnect();
        stopLive(result);
      })
      .catch((e) => {
        showApiError("stopLiveWithApi: " + e.message);
        stopLive({ status: "cancelled" });
      });
  }

  // Override stopLive to call API first
  const originalStopLive = stopLive;
  window.stopLive = function () {
    if (isLiveRunActive()) {
      stopLiveWithApi();
    } else {
      originalStopLive();
    }
  };

  async function reRunFromId(runId) {
    if (!runId) return;
    try {
      const config = await api.getRunConfig(runId);
      await openNewRunModal();
      applyRunConfigToModal(config);
    } catch (err) {
      alert("Failed to load run config: " + err.message);
    }
  }

  function applyRunConfigToModal(config) {
    if (!config) return;
    const selectedModels = new Map(
      (config.models || [])
        .filter((model) => model && model.id)
        .map((model) => [String(model.id), model])
    );
    document
      .querySelectorAll("#run-modal .modal-two-col > div:first-child .check-list input")
      .forEach((cb) => {
        try {
          const entry = JSON.parse(cb.dataset.entry || "{}");
          cb.checked = entry.id ? selectedModels.has(String(entry.id)) : false;
        } catch (_) {
          cb.checked = false;
        }
      });
    renderModalHarnessList();
    const selectedAgents = new Set((config.agents || []).map(String));
    document.querySelectorAll("#modal-harness-list input").forEach((cb) => {
      cb.checked = selectedAgents.has(String(cb.dataset.id || ""));
    });
      const promptEl = document.getElementById("modal-prompt");
      const iterEl = document.getElementById("mi-iters");
      const warmupEl = document.getElementById("mi-warmup");
      if (promptEl && config.prompt != null) promptEl.value = config.prompt;
      if (iterEl && config.iterations != null) iterEl.value = config.iterations;
      if (warmupEl && config.warmup != null) warmupEl.value = config.warmup;
  }
  window.reRunFromId = reRunFromId;
  window.reRunSelected = function () {
    return reRunFromId(appState.selectedRunId);
  };

  async function exportRun(runId) {
    if (!runId) return;
    try {
      const results = await api.getResults(runId);
      const blob = new Blob([JSON.stringify(results, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bench-results-${runId}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("Failed to export run: " + err.message);
    }
  }
  window.exportRun = exportRun;
  window.exportSelectedRun = function () {
    return exportRun(appState.selectedRunId);
  };

  // ── Configure: harnesses (API-driven) ──────────────────────────

  async function refreshDetection() {
    try {
      appState.detection = await api.detect();
      renderHarnesses();
    } catch (e) {
      showApiError("refreshDetection: " + e.message);
    }
  }

  function renderHarnesses() {
    const list = document.getElementById("harness-list");
    if (!list) return;

    if (!appState.detection) {
      list.innerHTML =
        '<div class="scanning-row"><div class="scanning-dot"></div>Scanning for harnesses\u2026</div>';
      return;
    }

    const agents = appState.detection.agents || [];
    const backends = appState.detection.backends || [];

    list.innerHTML = [
      ...agents.map((a) => ({
        id: a.id,
        abbr: (a.id || "").substring(0, 2).toUpperCase(),
        name: a.name || a.id,
        desc: a.desc || a.id,
        status: a.status || "installed",
        version: a.version || "",
        cmd: a.install_cmd || null,
        docs: a.docs || null,
      })),
      ...backends.map((b) => ({
        id: b.id,
        abbr: (b.id || "").substring(0, 2).toUpperCase(),
        name: b.name || b.id,
        desc: b.desc || b.id,
        status: b.status || "installed",
        version: b.version || "",
        cmd: b.install_cmd || null,
        docs: b.docs || null,
      })),
    ]
      .map((h) => {
        const installed = h.status === "installed";
        return `
        <div class="harness-row" id="hr-${escapeAttr(h.id)}">
          <div class="harness-icon">${escapeHtml(h.abbr)}</div>
          <div class="harness-info">
            <div class="harness-name">${escapeHtml(h.name || h.id)}</div>
            <div class="harness-desc">${escapeHtml(h.desc || "")}</div>
            <div class="harness-status-row">
              <div class="harness-sdot" style="background:${
                installed ? "var(--sage)" : "var(--ink-3)"
              }"></div>
              <span class="harness-stext ${installed ? "ok" : "off"}">
                ${escapeHtml(installed ? "installed" + (h.version ? " \u00b7 " + h.version : "") : "not installed")}
              </span>
            </div>
          </div>
          <button class="btn-harness-action" id="hbtn-${escapeAttr(h.id)}"
            onclick="${handlerAttr(
              installed
                ? `redetectOne(${jsString(h.id)})`
                : `toggleDrawer(${jsString(h.id)})`
            )}">
            ${installed ? "Re-detect" : "Install \u2193"}
          </button>
        </div>
        ${
          !installed
            ? `
        <div class="install-drawer" id="hd-${escapeAttr(h.id)}">
          <div class="install-drawer-title">Install ${escapeHtml(h.name || h.id)}</div>
          ${
            h.cmd
              ? `<div class="install-cmd-wrap">
              <span class="install-cmd">${escapeHtml(h.cmd)}</span>
              <button class="btn-copy" onclick="${handlerAttr(`window.copyCmd(${jsString(h.cmd)}, this)`)}">copy</button>
            </div>`
              : ""
          }
          <div class="install-hint">
            Run in your terminal, then click Re-detect when done.
            ${(h.docs
              ? `<br><a href="${escapeAttr(h.docs)}" target="_blank">\u2192 ${
                  escapeHtml(h.name || h.id)
                } docs \u2197</a>`
              : "")}
          </div>
        </div>`
            : ""
        }`;
      })
      .join("");
  }

  function toggleDrawer(id) {
    const d = document.getElementById("hd-" + id);
    const b = document.getElementById("hbtn-" + id);
    if (!d) return;
    const open = d.classList.toggle("open");
    b.textContent = open ? "Install \u2191" : "Install \u2193";
  }
  window.toggleDrawer = toggleDrawer;

  function redetectOne(id) {
    const row = document.getElementById("hr-" + id);
    const btn = document.getElementById("hbtn-" + id);
    const dot = row.querySelector(".harness-sdot");
    const txt = row.querySelector(".harness-stext");
    txt.textContent = "detecting\u2026";
    txt.className = "harness-stext scanning";
    btn.disabled = true;
    // Actually call API to re-detect
    refreshDetection();
  }
  window.redetectOne = redetectOne;

  async function redetectAll() {
    const btn = document.getElementById("btn-redetect");
    btn.disabled = true;
    btn.textContent = "Scanning\u2026";
    document.getElementById("harness-list").innerHTML =
      '<div class="scanning-row"><div class="scanning-dot"></div>Scanning for harnesses\u2026</div>';
    await refreshDetection();
    btn.disabled = false;
    btn.textContent = "Re-detect all";
  }
  window.redetectAll = redetectAll;

  function copyCmd(text, btn) {
    navigator.clipboard
      .writeText(text)
      .catch(() => {})
      .then(() => {
        const orig = btn.textContent;
        btn.textContent = "copied!";
        setTimeout(() => (btn.textContent = orig), 1500);
      });
  }
  window.copyCmd = copyCmd;

  // ── Boot ───────────────────────────────────────────────────────

  async function bootApp() {
    try {
      // Check health
      await api.health();
    } catch (e) {
      console.warn("[bench] API not reachable at /api/health - running offline");
      // Fall back to static/offline mode - UI is still usable
      renderHarnesses();
      renderRunHistory();
      return;
    }

    // Load runs, detection, config in parallel
    try {
      const [runs, detection, config] = await Promise.all([
        api.listRuns(),
        api.detect().catch(() => null),
        api.getConfig().catch(() => null),
      ]);

      appState.runs = runs || [];
      appState.detection = detection;
      appState.config = config;

      const running = appState.runs.find((r) => r.status === "running");

      if (running) {
        appState.selectedRunId = running.run_id;
        setLiveState();
        liveTimer = setInterval(refreshRuns, 5000);
      } else {
        appState.selectedRunId = null;
        clearDashboard();
        setIdleState();
      }

      renderRunHistory();
      renderHarnesses();

      // Connect SSE for live updates
      appState.liveSseDisconnect = api.connectEvents((event) => {
        handleProgressEvent(event);
        if (
          event.type === "results" ||
          event.type === "results_written"
        ) {
          setTimeout(refreshRuns, 500);
        }
      });

      // Poll runs periodically
      setInterval(refreshRuns, 10000);
    } catch (e) {
      showApiError("bootApp: " + e.message);
      renderRunHistory();
      renderHarnesses();
    }
  }

  // Expose for testing / debug
  window.benchApp = {
    boot: bootApp,
    state: appState,
    api,
    test: {
      refreshRuns,
      renderDashboard,
      clearDashboard,
      renderLeaderboard,
      renderModalModelPicker,
      renderModelCheckItem,
      renderRawOutputs,
      selectRawOutput,
      renderRunHistory,
      handleRunRowClick,
      clearRunHistory,
      handleModelSearchKeydown,
      renderLiveView,
      expandLivePlan,
      appendLiveLog,
      renderLiveLog,
      updateLiveStopControls,
      resetLiveRun,
      handleProgressEvent,
      updateLiveButton,
      markLiveStopped,
      switchView,
      switchMetric,
      startBenchmark,
      escapeHtml,
      escapeAttr,
      jsString,
      cssString,
      handlerAttr,
      timeAgo,
      parseTimestamp,
      mergeModelEntries,
      selectedModalBackends,
    },
  };

  // Init configure on first load
  document.addEventListener("DOMContentLoaded", () => {
    bootApp();
  });

  // If DOM is already ready, boot immediately
  if (document.readyState !== "loading") {
    bootApp();
  }
})();
