import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }

  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
    this._sync();
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
    this._sync();
  }

  contains(name) {
    return this.values.has(name);
  }

  toggle(name, force) {
    const shouldAdd = force === undefined ? !this.values.has(name) : !!force;
    if (shouldAdd) this.values.add(name);
    else this.values.delete(name);
    this._sync();
    return shouldAdd;
  }

  _sync() {
    this.element._className = [...this.values].join(" ");
  }
}

class Element {
  constructor(tagName = "div", ownerDocument = null) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.classList = new ClassList(this);
    this._className = "";
    this._id = "";
    this._innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.onclick = null;
  }

  set id(value) {
    this._id = String(value || "");
    if (this.ownerDocument && this._id) {
      this.ownerDocument._ids.set(this._id, this);
    }
  }

  get id() {
    return this._id;
  }

  set className(value) {
    this._className = String(value || "");
    this.classList.setFromString(this._className);
  }

  get className() {
    return this._className;
  }

  set innerHTML(value) {
    this._innerHTML = String(value || "");
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  after(node) {
    if (!this.parentNode) return;
    node.parentNode = this.parentNode;
    const index = this.parentNode.children.indexOf(this);
    this.parentNode.children.splice(index + 1, 0, node);
  }

  remove() {
    if (!this.parentNode) return;
    const index = this.parentNode.children.indexOf(this);
    if (index >= 0) this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }

  closest(selector) {
    let node = this;
    while (node) {
      if (matches(node, selector)) return node;
      node = node.parentNode;
    }
    return null;
  }

  querySelector(selector) {
    return queryAll(this, selector)[0] || null;
  }

  querySelectorAll(selector) {
    return queryAll(this, selector);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "id") this.id = value;
    if (name === "class") this.className = value;
  }
}

class Document extends Element {
  constructor() {
    super("#document", null);
    this.ownerDocument = this;
    this._ids = new Map();
    this.readyState = "loading";
    this.body = this.createElement("body");
    this.appendChild(this.body);
    this._listeners = {};
  }

  createElement(tagName) {
    return new Element(tagName, this);
  }

  getElementById(id) {
    return this._ids.get(id) || null;
  }

  addEventListener(name, handler) {
    this._listeners[name] = handler;
  }
}

function matches(element, selector) {
  if (!selector) return false;
  if (selector === ".modal-two-col > div:first-child") {
    return (
      element.tagName.toLowerCase() === "div" &&
      element.parentNode &&
      element.parentNode.classList.contains("modal-two-col") &&
      element.parentNode.children[0] === element
    );
  }
  if (selector.endsWith(":checked")) {
    const baseSelector = selector.slice(0, -":checked".length);
    return matches(element, baseSelector) && !!element.checked;
  }
  if (selector.startsWith("#")) return element.id === selector.slice(1);
  if (selector.startsWith(".")) return element.classList.contains(selector.slice(1));
  if (selector.includes(".")) {
    const [tag, klass] = selector.split(".");
    return element.tagName.toLowerCase() === tag && element.classList.contains(klass);
  }
  return element.tagName.toLowerCase() === selector.toLowerCase();
}

function queryAll(root, selector) {
  const selectors = selector.split(",").map((s) => s.trim());
  const out = [];
  const visit = (node) => {
    if (selectors.some((s) => matches(node, s))) out.push(node);
    node.children.forEach(visit);
  };
  root.children.forEach(visit);
  return out;
}

function add(document, parent, tag, { id, className, textContent } = {}) {
  const el = document.createElement(tag);
  if (id) el.id = id;
  if (className) el.className = className;
  if (textContent) el.textContent = textContent;
  parent.appendChild(el);
  return el;
}

function buildDocument() {
  const document = new Document();
  const history = add(document, document.body, "div", { className: "history" });
  const historyHead = add(document, history, "div", { className: "history-head" });
  add(document, historyHead, "div", { className: "history-label", textContent: "Run History" });
  add(document, document.body, "div", { id: "sidebar" });
  add(document, document.body, "button", { id: "btn-new" });
  add(document, document.body, "button", { id: "btn-compare-cta" });
  add(document, document.body, "button", { id: "btn-clear-history" });
  const modal = add(document, document.body, "div", { id: "run-modal" });
  const modalCols = add(document, modal, "div", { className: "modal-two-col" });
  add(document, modalCols, "div");
  add(document, modalCols, "div");
  add(document, document.body, "div", { id: "topbar" });
  add(document, document.body, "div", { id: "topbar-title" });
  add(document, document.body, "div", { id: "topbar-meta" });
  add(document, document.body, "div", { id: "live-run-name" });
  add(document, document.body, "div", { id: "stat-strip" });
  add(document, document.body, "div", { id: "matrix-label" });
  add(document, document.body, "div", { className: "matrix-scroll" });
  add(document, document.body, "tbody", { id: "leaderboard-body" });
  add(document, document.body, "div", { className: "prompt-body" });
  add(document, document.body, "div", { className: "prompt-foot" });
  add(document, document.body, "select", { id: "raw-output-select" });
  add(document, document.body, "div", { id: "raw-output-meta" });
  add(document, document.body, "pre", { id: "raw-output-body" });
  add(document, document.body, "div", { id: "cell-popover" });
  add(document, document.body, "div", { id: "progress-count" });
  add(document, document.body, "div", { id: "progress-fill" });
  add(document, document.body, "div", { id: "progress-agent" });
  add(document, document.body, "div", { id: "live-view-sub" });
  add(document, document.body, "div", { id: "live-summary-done" });
  add(document, document.body, "div", { id: "live-summary-issues" });
  add(document, document.body, "div", { id: "live-summary-running" });
  add(document, document.body, "div", { id: "live-summary-pending" });
  add(document, document.body, "div", { id: "live-detail-title" });
  add(document, document.body, "div", { id: "live-detail-sub" });
  add(document, document.body, "div", { id: "live-test-list" });
  add(document, document.body, "div", { id: "live-log-body" });
  add(document, document.body, "div", { id: "live-log-count" });
  add(document, document.body, "button", { id: "live-panel-stop", className: "live-stop-action" });
  add(document, document.body, "button", { className: "seg-btn" }).dataset.metric = "toks";
  add(document, document.body, "button", { className: "seg-btn" }).dataset.metric = "wall";
  add(document, document.body, "div", { className: "nav-item" }).dataset.view = "dashboard";
  add(document, document.body, "div", { className: "nav-item" }).dataset.view = "live";
  add(document, document.body, "div", { className: "view", id: "view-dashboard" });
  add(document, document.body, "div", { className: "view", id: "view-live" });
  return document;
}

function response(body) {
  return {
    ok: true,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

async function loadUi({ fetchImpl, EventSourceImpl, setTimeoutImpl } = {}) {
  const document = buildDocument();
  const window = {
    document,
    CSS: { escape: (value) => String(value).replace(/["\\]/g, "\\$&") },
    addEventListener: () => {},
  };
  const context = {
    window,
    document,
    Date,
    URLSearchParams,
    console,
    navigator: { clipboard: { writeText: async () => {} } },
    EventSource: EventSourceImpl || class {
      addEventListener() {}
      close() {}
    },
    fetch: fetchImpl || (async () => response({})),
    alert: () => {},
    confirm: () => true,
    setInterval: () => 1,
    clearInterval: () => {},
    setTimeout: setTimeoutImpl || ((fn) => {
      fn();
      return 1;
    }),
  };
  vm.createContext(context);
  vm.runInContext(readFileSync("ai_bench/static/bench-web-ui.js", "utf8"), context);
  await Promise.resolve();
  return { window, document };
}

const payload = {
  summary: {
    run_id: "result-run",
    fastest_wall_s: 0.42,
    peak_throughput: 12.3,
    best_ttft: 0.12,
    combo_count: 1,
  },
  matrix: [
    {
      model: "model-a",
      agent: "pi",
      wall_s: 0.42,
      throughput_tok_s: 12.3,
      ttft_s: 0.12,
    },
  ],
  leaderboard: [
    {
      agent: "pi",
      wall_s: 0.42,
      throughput_tok_s: 12.3,
      ttft_s: 0.12,
    },
  ],
  prompt: "Build it.",
  raw_outputs: [
    {
      index: 0,
      label: "pi+ollama+model-a",
      iteration: 0,
      output_file: "pi+ollama+model-a__iter-0.txt",
    },
  ],
};

test("renderDashboard renders stats, matrix, leaderboard, and prompt", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.renderDashboard(payload);

  assert.match(document.getElementById("stat-strip").innerHTML, /12\.3/);
  assert.match(document.querySelector(".matrix-scroll").innerHTML, /model-a/);
  assert.match(document.getElementById("leaderboard-body").innerHTML, /0\.12s/);
  assert.equal(document.querySelector(".prompt-body").textContent, "Build it.");
  assert.match(document.getElementById("raw-output-select").innerHTML, /pi\+ollama\+model-a/);
});

test("timeAgo renders friendly relative run history dates", async () => {
  const { window } = await loadUi();
  const originalNow = Date.now;
  Date.now = () => new Date(2026, 4, 22, 19, 42, 5).getTime();

  try {
    assert.equal(window.benchApp.test.timeAgo("20260522-194128"), "37s ago");
    assert.equal(window.benchApp.test.timeAgo("20260522-194005"), "2 mins ago");
    assert.equal(window.benchApp.test.timeAgo("20260522-164205"), "3 hrs ago");
    assert.equal(window.benchApp.test.timeAgo("20260518-194205"), "4 days ago");
  } finally {
    Date.now = originalNow;
  }
});

test("renderRunHistory uses friendly relative dates", async () => {
  const { window, document } = await loadUi();
  const originalNow = Date.now;
  Date.now = () => new Date(2026, 4, 22, 19, 42, 5).getTime();

  try {
    window.benchApp.state.runs = [
      {
        run_id: "run-1",
        name: "friendly run",
        status: "completed",
        timestamp: "20260522-194128",
      },
    ];
    window.benchApp.test.renderRunHistory();

    const renderedRows = document.querySelector(".history").children
      .map((child) => child.innerHTML)
      .join("\n");
    assert.match(renderedRows, /37s ago/);
  } finally {
    Date.now = originalNow;
  }
});

test("renderRunHistory keeps newest API run at the top", async () => {
  const { window, document } = await loadUi();

  window.benchApp.state.runs = [
    {
      run_id: "new",
      name: "newest run",
      status: "completed",
      timestamp: "20260522-194205",
    },
    {
      run_id: "old",
      name: "older run",
      status: "completed",
      timestamp: "20260521-194205",
    },
  ];
  window.benchApp.test.renderRunHistory();

  const firstRow = document.querySelector(".history").children.find((child) =>
    child.classList.contains("run-row")
  );
  assert.match(firstRow.innerHTML, /newest run/);
});

test("run row click toggles compare selection instead of navigating", async () => {
  const { window, document } = await loadUi();
  const history = document.querySelector(".history");
  const row = add(document, history, "div", { className: "run-row" });
  row.dataset.runId = "run-1";
  const checkbox = add(document, row, "input", { className: "run-check" });
  const cta = document.getElementById("btn-compare-cta");

  window.benchApp.test.switchView("compare");
  window.benchApp.test.handleRunRowClick("run-1", row);

  assert.equal(checkbox.checked, true);
  assert.equal(window.benchApp.state.selectedRunId, null);
  assert.equal(cta.textContent, "Select one more\u2026");

  window.benchApp.test.handleRunRowClick("run-1", row);

  assert.equal(checkbox.checked, false);
  assert.equal(cta.textContent, "Select runs to compare");
});

test("clearRunHistory deletes completed runs and leaves running runs", async () => {
  const calls = [];
  const { window } = await loadUi({
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, method: options.method || "GET" });
      if (url === "/api/runs" && !options.method) {
        return response([
          {
            run_id: "active",
            name: "active run",
            status: "running",
            timestamp: "20260522-194205",
          },
        ]);
      }
      return response({ ok: true });
    },
  });

  window.benchApp.state.runs = [
    {
      run_id: "done-1",
      name: "done one",
      status: "completed",
      timestamp: "20260522-194128",
    },
    {
      run_id: "active",
      name: "active run",
      status: "running",
      timestamp: "20260522-194205",
    },
    {
      run_id: "done-2",
      name: "done two",
      status: "cancelled",
      timestamp: "20260522-194305",
    },
  ];
  window.benchApp.state.selectedRunId = "done-1";

  await window.benchApp.test.clearRunHistory();

  assert.deepEqual(
    calls
      .filter((call) => call.method === "DELETE")
      .map((call) => call.url),
    ["/api/runs/done-1", "/api/runs/done-2"]
  );
  assert.equal(window.benchApp.state.selectedRunId, null);
  assert.equal(window.benchApp.state.runs.length, 1);
  assert.equal(window.benchApp.state.runs[0].run_id, "active");
});

test("pressing enter in model search input triggers search", async () => {
  const calls = [];
  const { window, document } = await loadUi({
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, method: options.method || "GET" });
      return response({ results: [] });
    },
  });
  const input = add(document, document.body, "input", { id: "model-search-omlx" });
  input.value = "qwen";
  add(document, document.body, "div", { id: "model-search-results-omlx" });
  let prevented = false;

  await window.benchApp.test.handleModelSearchKeydown(
    { key: "Enter", preventDefault: () => { prevented = true; } },
    "omlx"
  );

  assert.equal(prevented, true);
  assert.equal(calls[0].url, "/api/models/search?backend=omlx&q=qwen");
});

test("installed models are unchecked by default in new run picker", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.renderModalModelPicker({
    backends: {
      ollama: [
        {
          backend: "ollama",
          id: "qwen3:1.7b",
          label: "qwen3-1.7b",
          source: "installed",
          model_entry: { id: "qwen3-1.7b", ollama: "qwen3:1.7b" },
        },
      ],
    },
  });

  const modelColumn = document.getElementById("run-modal").querySelector(".modal-two-col").children[0];
  assert.doesNotMatch(modelColumn.innerHTML, /checked/);
});

test("timeAgo keeps invalid timestamps visible", async () => {
  const { window } = await loadUi();

  assert.equal(window.benchApp.test.timeAgo("not-a-date"), "not-a-date");
});

test("mergeModelEntries combines aliases selected from multiple backends", async () => {
  const { window } = await loadUi();

  const merged = window.benchApp.test.mergeModelEntries([
    { id: "qwen3-4b", ollama: "qwen3:4b" },
    { id: "qwen3-4b", lmstudio: "lmstudio-community/Qwen3-4B-GGUF" },
    { id: "coder", omlx: "Qwen-Coder-MLX", omlx_hf: "mlx-community/Qwen-Coder-MLX" },
  ]);

  assert.deepEqual(JSON.parse(JSON.stringify(merged)), [
    {
      id: "qwen3-4b",
      ollama: "qwen3:4b",
      lmstudio: "lmstudio-community/Qwen3-4B-GGUF",
    },
    {
      id: "coder",
      omlx: "Qwen-Coder-MLX",
      omlx_hf: "mlx-community/Qwen-Coder-MLX",
    },
  ]);
});

test("switchMetric re-renders from stored matrix data", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.renderDashboard(payload);
  window.benchApp.test.switchMetric("wall");

  assert.match(document.querySelector(".matrix-scroll").innerHTML, /s wall/);
  assert.match(document.querySelector(".matrix-scroll").innerHTML, /0\.4/);
});

test("rendered API strings are escaped before entering innerHTML", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.renderDashboard({
    ...payload,
    matrix: [{ ...payload.matrix[0], model: "<img src=x>", agent: "pi<script>" }],
    leaderboard: [{ ...payload.leaderboard[0], agent: "pi<script>" }],
  });

  const rendered = [
    document.querySelector(".matrix-scroll").innerHTML,
    document.getElementById("leaderboard-body").innerHTML,
  ].join("\n");
  assert.match(rendered, /&lt;img src=x&gt;/);
  assert.match(rendered, /pi&lt;script&gt;/);
  assert.doesNotMatch(rendered, /<img src=x>/);
  assert.doesNotMatch(rendered, /pi<script>/);
});

test("combo results can sort by agent", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.renderDashboard({
    ...payload,
    leaderboard: [
      { agent: "pi", model: "model-b", wall_s: 2, throughput_tok_s: 20, ttft_s: 0.2 },
      { agent: "direct", model: "model-a", wall_s: 1, throughput_tok_s: 10, ttft_s: 0.1 },
    ],
  });
  window.sortBy("agent");

  const html = document.getElementById("leaderboard-body").innerHTML;
  assert.ok(html.indexOf("direct") < html.indexOf("pi"));
});

test("combo result sort toggles direction on repeated column clicks", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.renderDashboard({
    ...payload,
    leaderboard: [
      { agent: "alpha", model: "model-a", wall_s: 1, throughput_tok_s: 10, ttft_s: 0.1 },
      { agent: "zeta", model: "model-z", wall_s: 3, throughput_tok_s: 30, ttft_s: 0.3 },
    ],
  });

  window.sortBy("agent");
  let html = document.getElementById("leaderboard-body").innerHTML;
  assert.ok(html.indexOf("alpha") < html.indexOf("zeta"));

  window.sortBy("agent");
  html = document.getElementById("leaderboard-body").innerHTML;
  assert.ok(html.indexOf("zeta") < html.indexOf("alpha"));

  window.sortBy("wall");
  html = document.getElementById("leaderboard-body").innerHTML;
  assert.ok(html.indexOf("alpha") < html.indexOf("zeta"));

  window.sortBy("wall");
  html = document.getElementById("leaderboard-body").innerHTML;
  assert.ok(html.indexOf("zeta") < html.indexOf("alpha"));
});

test("refreshRuns recovers when a live web run disappears into a completed result", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    if (url === "/api/runs") {
      return response([
        {
          run_id: "result-run",
          name: "finished run",
          status: "completed",
          timestamp: "20260522-194205",
          iterations: 1,
          warmup: 1,
          combo_count: 1,
        },
      ]);
    }
    if (url === "/api/runs/result-run/results") return response(payload);
    return response({});
  };
  const { window, document } = await loadUi({ fetchImpl });
  window.benchApp.state.selectedRunId = "web-run-id";
  document.getElementById("topbar").classList.add("is-live");

  await window.benchApp.test.refreshRuns();

  assert.equal(window.benchApp.state.selectedRunId, "result-run");
  assert.equal(document.getElementById("topbar").classList.contains("is-live"), false);
  assert.equal(document.getElementById("topbar-title").textContent, "finished run");
  assert.match(document.querySelector(".matrix-scroll").innerHTML, /model-a/);
  assert.deepEqual(calls, [
    "/api/runs",
    "/api/runs/result-run/results",
    "/api/runs/result-run/raw-output?index=0",
  ]);
});

test("refreshRuns does not auto-select a historical run on cold start", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    if (url === "/api/runs") {
      return response([
        {
          run_id: "historical-run",
          name: "finished run",
          status: "completed",
          timestamp: "20260522-194205",
        },
      ]);
    }
    if (url === "/api/runs/historical-run/results") return response(payload);
    return response({});
  };
  const { window, document } = await loadUi({ fetchImpl });
  window.benchApp.test.renderDashboard(payload);

  await window.benchApp.test.refreshRuns();

  assert.equal(window.benchApp.state.selectedRunId, null);
  assert.deepEqual(calls, ["/api/runs"]);
  assert.equal(document.getElementById("stat-strip").innerHTML, "");
  assert.equal(document.querySelector(".matrix-scroll").innerHTML, "");
  assert.equal(document.getElementById("leaderboard-body").innerHTML, "");
});

test("live button replaces new-run CTA with stop action", async () => {
  const { window, document } = await loadUi();
  const button = document.getElementById("btn-new");
  let stopped = false;
  window.stopLive = () => {
    stopped = true;
  };

  window.benchApp.test.updateLiveButton(true);
  button.onclick();

  assert.equal(button.textContent, "Stop");
  assert.equal(button.classList.contains("stop"), true);
  assert.equal(stopped, true);

  window.benchApp.test.updateLiveButton(false);

  assert.equal(button.textContent, "+ New Benchmark Run");
  assert.equal(button.classList.contains("stop"), false);
});

test("live view renders completed, running, and pending tests from progress events", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("run name", 3);
  window.benchApp.test.handleProgressEvent({
    type: "iteration_complete",
    label: "pi+ollama+qwen",
    tag: "warmup-0",
    done: 1,
    total: 3,
    wall_s: 0.5,
  });
  window.benchApp.test.handleProgressEvent({
    type: "iteration_start",
    label: "direct+ollama+qwen",
    tag: "iter-0",
    done: 1,
    total: 3,
  });

  assert.equal(document.getElementById("live-summary-done").textContent, "1");
  assert.equal(document.getElementById("live-summary-issues").textContent, "0");
  assert.equal(document.getElementById("live-summary-running").textContent, "1");
  assert.equal(document.getElementById("live-summary-pending").textContent, "1");
  assert.match(document.getElementById("live-test-list").innerHTML, /pi\+ollama\+qwen/);
  assert.match(document.getElementById("live-test-list").innerHTML, /direct\+ollama\+qwen/);
  assert.match(document.getElementById("live-test-list").innerHTML, /Queued test 3/);
});

test("plan event renders queued test descriptions before tests start", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("run name", 4);
  window.benchApp.test.handleProgressEvent({
    type: "plan",
    total_runs: 4,
    warmup: 1,
    iterations: 1,
    planned: [
      { label: "pi+omlx+qwen", agent: "pi", backend: "omlx", model_id: "qwen" },
      { label: "direct+ollama+gemma", agent: "direct", backend: "ollama", model_id: "gemma" },
    ],
  });

  const list = document.getElementById("live-test-list").innerHTML;
  assert.match(list, /live-test-index/);
  assert.match(list, /pi\+omlx\+qwen/);
  assert.match(list, /warmup-0/);
  assert.match(list, /direct\+ollama\+gemma/);
  assert.doesNotMatch(list, /Pending test/);
});

test("live log events append CLI output", async () => {
  const { window, document } = await loadUi();
  const originalToLocale = Date.prototype.toLocaleTimeString;
  Date.prototype.toLocaleTimeString = () => "14:03:09";

  try {
    window.benchApp.test.handleProgressEvent({
      type: "log",
      stream: "stdout",
      line: "Plan: 2 combos x 3 runs = 6 total",
    });
    window.benchApp.test.handleProgressEvent({
      type: "log",
      stream: "stderr",
      line: "warning: backend slow to start",
    });

    assert.match(document.getElementById("live-log-body").innerHTML, /14:03:09/);
    assert.match(document.getElementById("live-log-body").innerHTML, /Plan: 2 combos/);
    assert.match(document.getElementById("live-log-body").innerHTML, /warning: backend slow/);
    assert.equal(document.getElementById("live-log-count").textContent, "2 lines");
  } finally {
    Date.prototype.toLocaleTimeString = originalToLocale;
  }
});

test("selectRawOutput lazily fetches output text", async () => {
  const { window, document } = await loadUi({
    fetchImpl: async (url) => {
      assert.equal(url, "/api/runs/result-run/raw-output?index=0");
      return response({ text: "<html>lazy output</html>", truncated: false });
    },
  });

  window.benchApp.state.selectedRunId = "result-run";
  window.benchApp.test.renderRawOutputs([
    {
      index: 0,
      label: "pi+ollama+model-a",
      iteration: 0,
      output_file: "pi+ollama+model-a__iter-0.txt",
    },
  ]);
  await window.benchApp.test.selectRawOutput("0");

  assert.equal(document.getElementById("raw-output-body").textContent, "<html>lazy output</html>");
  assert.equal(document.getElementById("raw-output-meta").textContent, "24 chars");
});

test("live view does not infer completed rows from aggregate progress alone", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("run name", 4);
  window.benchApp.test.handleProgressEvent({
    type: "iteration_start",
    label: "pi+ollama+qwen",
    tag: "warmup-0",
    done: 2,
    total: 4,
  });

  assert.equal(document.getElementById("live-summary-done").textContent, "0");
  assert.equal(document.getElementById("live-summary-issues").textContent, "0");
  assert.equal(document.getElementById("live-summary-running").textContent, "1");
  assert.equal(document.getElementById("live-summary-pending").textContent, "3");
});

test("live view does not mark the previous running row as passed when the next test starts", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("run name", 3);
  window.benchApp.test.handleProgressEvent({
    type: "iteration_start",
    label: "pi+ollama+qwen",
    tag: "warmup-0",
    done: 0,
    total: 3,
  });
  window.benchApp.test.handleProgressEvent({
    type: "iteration_start",
    label: "direct+ollama+qwen",
    tag: "iter-0",
    done: 1,
    total: 3,
  });

  const list = document.getElementById("live-test-list").innerHTML;
  assert.equal(document.getElementById("live-summary-done").textContent, "0");
  assert.equal(document.getElementById("live-summary-running").textContent, "1");
  assert.equal((list.match(/live-test-row running/g) || []).length, 1);
  assert.match(list, /unknown/);
});

test("warmup completions count as live completed tests", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("run name", 2);
  window.benchApp.test.handleProgressEvent({
    type: "iteration_start",
    label: "pi+ollama+qwen",
    tag: "warmup-0",
    done: 0,
    total: 2,
  });
  window.benchApp.test.handleProgressEvent({
    type: "iteration_complete",
    label: "pi+ollama+qwen",
    tag: "warmup-0",
    done: 1,
    total: 2,
    wall_s: 8.2,
  });

  assert.equal(document.getElementById("live-summary-done").textContent, "1");
  assert.equal(document.getElementById("live-summary-issues").textContent, "0");
  assert.equal(document.getElementById("live-summary-running").textContent, "0");
  assert.match(document.getElementById("live-test-list").innerHTML, /8\.2s/);
});

test("failed and empty completions show as issues instead of passed", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("run name", 2);
  window.benchApp.test.handleProgressEvent({
    type: "iteration_complete",
    label: "pi+lmstudio+qwen",
    tag: "iter-0",
    done: 1,
    total: 2,
    wall_s: 0.4,
    rc: 1,
    output_chars: 0,
  });
  window.benchApp.test.handleProgressEvent({
    type: "iteration_complete",
    label: "opencode+lmstudio+qwen",
    tag: "iter-0",
    done: 2,
    total: 2,
    wall_s: 0.8,
    rc: 0,
    output_chars: 0,
  });

  assert.equal(document.getElementById("live-summary-done").textContent, "0");
  assert.equal(document.getElementById("live-summary-issues").textContent, "2");
  assert.match(document.getElementById("live-test-list").innerHTML, /failed/);
  assert.match(document.getElementById("live-test-list").innerHTML, /empty/);
});

test("stopping a live run replaces the running topbar copy", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("demo run", 2);
  document.getElementById("topbar").classList.add("is-live");
  document.getElementById("topbar-title").textContent = "demo run · running";

  window.benchApp.test.markLiveStopped({ status: "cancelled", run_id: "run-1" });

  assert.equal(document.getElementById("topbar").classList.contains("is-live"), false);
  assert.equal(document.getElementById("topbar-title").textContent, "demo run stopped");
  assert.equal(document.getElementById("topbar-meta").textContent, "cancelled just now");
  assert.equal(document.getElementById("btn-new").textContent, "+ New Benchmark Run");
  assert.equal(document.getElementById("live-panel-stop").disabled, true);
  assert.equal(document.getElementById("live-panel-stop").textContent, "Stopped");
});

test("completed status clears stale live progress", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("demo run", 3);
  document.getElementById("topbar").classList.add("is-live");
  window.benchApp.test.handleProgressEvent({
    type: "iteration_start",
    label: "pi+ollama+qwen",
    tag: "iter-0",
    done: 1,
    total: 3,
  });

  window.benchApp.test.handleProgressEvent({ type: "status", status: "completed" });

  assert.equal(document.getElementById("topbar").classList.contains("is-live"), false);
  assert.equal(window.benchApp.state.currentRun, null);
  assert.equal(window.benchApp.state.liveTotal, 0);
  assert.equal(window.benchApp.state.liveDone, 0);
  assert.equal(document.getElementById("progress-count").textContent, "0 / 0");
  assert.equal(document.getElementById("live-summary-running").textContent, "0");
  assert.equal(document.getElementById("live-summary-pending").textContent, "0");
  assert.match(document.getElementById("live-test-list").innerHTML, /No live run is active/);
});

test("plan event replaces an initial progress-total guess", async () => {
  const { window, document } = await loadUi();

  window.benchApp.test.resetLiveRun("run name", 99);
  window.benchApp.test.handleProgressEvent({
    type: "plan",
    total_runs: 8,
  });

  assert.equal(window.benchApp.state.liveTotal, 8);
  assert.equal(document.getElementById("progress-count").textContent, "0 / 8");
  assert.equal(document.getElementById("live-summary-pending").textContent, "8");
});

test("connectEvents retries on error until disconnected", async () => {
  const created = [];
  const timers = [];
  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.closed = false;
      this.listeners = {};
      created.push(this);
    }
    addEventListener(name, handler) {
      this.listeners[name] = handler;
    }
    close() {
      this.closed = true;
    }
  }

  const { window } = await loadUi({
    EventSourceImpl: FakeEventSource,
    setTimeoutImpl: (fn, delay) => {
      timers.push({ fn, delay });
      return timers.length;
    },
  });

  const disconnect = window.benchApi.connectEvents(() => {});
  assert.equal(created.length, 1);
  created[0].onerror();
  assert.equal(created[0].closed, true);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 500);

  timers[0].fn();
  assert.equal(created.length, 2);

  disconnect();
  created[1].onerror();
  assert.equal(timers.length, 1);
});
