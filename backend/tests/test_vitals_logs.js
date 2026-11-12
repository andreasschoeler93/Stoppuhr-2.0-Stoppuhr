const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadApp() {
  const cards = [];
  const list = { innerHTML: "", appendChild: card => cards.push(card) };
  const pool = { addEventListener() {} };
  const elements = { tasterList: list };
  const document = {
    addEventListener() {},
    getElementById: id => elements[id] || pool,
    createElement: () => ({
      classList: { add() {} },
      dataset: {},
      addEventListener() {},
    }),
  };
  const context = vm.createContext({ document, localStorage: { getItem: () => null }, console });
  const app = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
  vm.runInContext(app, context);
  return { context, cards, elements };
}

test("Taster logs are below WLAN and belong to each Taster, including offline devices", () => {
  const { context } = loadApp();
  vm.runInContext(`vitalsData = { tasters: [
    { letter: "A", mac: "AA:BB:CC:DD:EE:FF", online: true, rssi: -50 },
    { letter: "B", mac: "11:22:33:44:55:66", online: false, rssi: -70 },
    { letter: "C", online: false }
  ] }`, context);
  const html = vm.runInContext("vitalsStatusHtml()", context);
  const rows = [...html.matchAll(/<tr>(.*?)<\/tr>/g)].map(match => match[1]);
  const wlan = rows.findIndex(row => row.includes(">WLAN</th>"));
  const logs = rows.findIndex(row => row.includes(">Logs</th>"));
  assert.ok(wlan >= 0);
  assert.equal(logs, wlan + 1);
  assert.match(rows[logs], /\/api\/device-logs\/taster\/AA%3ABB%3ACC%3ADD%3AEE%3AFF/);
  assert.match(rows[logs], /\/api\/device-logs\/taster\/11%3A22%3A33%3A44%3A55%3A66/);
  assert.equal((rows[logs].match(/ download /g) || []).length, 2);
  assert.match(rows[logs], /<td class="text-center text-nowrap text-muted">–<\/td>/);
});

test("Alle starten sends one all-slots request and waits for completion", async () => {
  const { context, elements } = loadApp();
  const all = { disabled: false, dataset: {}, hasAttribute: name => name === "data-wake-all" };
  const single = { disabled: false };
  const status = {};
  elements.manualWakeButtons = { querySelectorAll: () => [all, single] };
  elements.manualWakeStatus = status;
  context.testEvent = { target: { closest: () => all } };
  vm.runInContext(`apiPost = async (path, body) => {
    if (path !== "/api/charger/wake" || body.all !== true) throw new Error("wrong request");
    if (!document.getElementById("manualWakeButtons").querySelectorAll().every(b => b.disabled))
      throw new Error("buttons not disabled");
    return { id: "request", timeout_ms: 360000 };
  };
  waitForChargerWake = async (id, timeout) => {
    if (id !== "request" || timeout !== 360000) throw new Error("wrong wait");
    return { status: "completed" };
  };`, context);
  await vm.runInContext("handleManualWake(testEvent)", context);
  assert.equal(status.textContent, "Alle Plätze: Wecksequenz abgeschlossen.");
  assert.equal(all.disabled, false);
  assert.equal(single.disabled, false);
});

test("Alle starten surfaces a firmware compatibility error", async () => {
  const { context, elements } = loadApp();
  const all = { disabled: false, dataset: {}, hasAttribute: () => true };
  const status = {};
  elements.manualWakeButtons = { querySelectorAll: () => [all] };
  elements.manualWakeStatus = status;
  context.testEvent = { target: { closest: () => all } };
  vm.runInContext('apiPost = async () => { throw new Error("Firmware ab v0.7.24 erforderlich"); };', context);
  await vm.runInContext("handleManualWake(testEvent)", context);
  assert.match(status.textContent, /Firmware ab v0\.7\.24 erforderlich/);
  assert.equal(all.disabled, false);
});

test("Taster cards do not contain a log download link", () => {
  const { context, cards } = loadApp();
  vm.runInContext(`buttons = [{ id: "1", letter: "A", mac: "AA:BB:CC:DD:EE:FF", role: "none" }];
    getSlotForButton = () => ({ slot: null });
    tasterLevel = () => null;
    vitalsHtml = () => "";
    renderButtonList();`, context);
  assert.equal(cards.length, 1);
  assert.doesNotMatch(cards[0].innerHTML, /device-logs|Logs herunterladen/);
});

test("Ladekoffer current is shown only when valid and online", () => {
  const { context } = loadApp();
  vm.runInContext(`chargerData = {
    known: true, online: true, state: "ruhig", messages: [],
    status: { slots: [], current_ok: true, current_saturated: false, current_a: 0.42 }
  };`, context);
  assert.match(vm.runInContext("chargerStatusHtml()", context), /Gesamtstrom: <strong>0\.420 A/);
  vm.runInContext("chargerData.status.current_saturated = true", context);
  assert.match(vm.runInContext("chargerStatusHtml()", context), /Messbereichsende – Strom unbekannt/);
  vm.runInContext("chargerData.online = false", context);
  assert.match(vm.runInContext("chargerStatusHtml()", context), /nicht verfügbar \(Ladekoffer offline\)/);
  vm.runInContext("chargerData.online = true; chargerData.status.current_ok = false; chargerData.status.current_saturated = false", context);
  assert.match(vm.runInContext("chargerStatusHtml()", context), /Gesamtstrom: <strong>nicht verfügbar/);
});

test("Current chart does not bridge an invalid measurement", () => {
  const { context, elements } = loadApp();
  const strokes = [];
  const g = {
    scale() {}, clearRect() {}, fillText() {}, beginPath() {}, stroke() {},
    save() {}, restore() {}, setLineDash() {},
    moveTo(x, y) { strokes.push(["move", x, y]); },
    lineTo(x, y) { strokes.push(["line", x, y]); },
  };
  elements["vc-charger-current"] = { clientWidth: 400, clientHeight: 180, getContext: () => g };
  context.window = { devicePixelRatio: 1 };
  vm.runInContext(`vitalsData = { t1: 10000, hours: 1, starts: [] };
    drawVitalChart({ id: "charger-current", idx: 1, decimals: 2 },
      [{ label: "Strom", color: "red", points: [[1000, 0.1], [2000, null], [3000, 0.2]] }]);`, context);
  assert.deepEqual(strokes.slice(-2).map(s => s[0]), ["move", "move"]);
});

test("Archived charger history accepts old points and preserves current gaps", () => {
  const { context } = loadApp();
  vm.runInContext(`buildArchiveVitals({
    id: "archive", ended_ts: 5000,
    charger: [[1000, 20, 40], [2000, 20, 40, 0.3], [3000, 20, 40, null]]
  });`, context);
  assert.equal(vm.runInContext("chargerCurrentSeries[0].points[0][1]", context), null);
  assert.equal(vm.runInContext("chargerCurrentSeries[0].points[1][1]", context), 0.3);
  assert.equal(vm.runInContext("chargerCurrentSeries[0].points[2][1]", context), null);
});
