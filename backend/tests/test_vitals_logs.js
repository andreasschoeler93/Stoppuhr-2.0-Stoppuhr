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

test("battery warning uses raw reading while displaying smoothed percent", () => {
  const { context } = loadApp();
  vm.runInContext(`vitalsData = { tasters: [
    { letter: "A", mac: "AA:BB:CC:DD:EE:FF", online: true, battery: 50, battery_raw: 10 }
  ] };`, context);
  assert.match(vm.runInContext("vitalsStatusHtml()", context), /val-danger[^>]*>50 %/);
  assert.match(vm.runInContext("sensorAlerts(vitalsData.tasters, [])[0].text", context), /10 %/);
  assert.match(vm.runInContext('vitalsHtml({online:true,battery_percent:50,battery_raw:10})', context), /val-danger[^>]*>50%/);
  assert.equal(vm.runInContext('tasterLevel({online:true,battery_percent:50,battery_raw:10}, true)', context), "danger");
  vm.runInContext("delete vitalsData.tasters[0].battery_raw; vitalsData.tasters[0].battery = 10", context);
  assert.match(vm.runInContext("sensorAlerts(vitalsData.tasters, [])[0].text", context), /10 %/);
});

test("lane vitals show only individually flagged values and the actual battery warning value", () => {
  const { context } = loadApp();
  vm.runInContext(`var sample = {
    online: true, battery_percent: 60, battery_raw: 60, vbat: 4.1,
    rssi_dbm: -50, ssid: "WLAN", temp: 25, humidity: 40
  };`, context);
  assert.equal(vm.runInContext("vitalWarningsHtml(sample)", context), "");
  vm.runInContext("sample.battery_raw = 25; sample.vbat = 3.2; sample.rssi_dbm = -75; sample.temp = 55; sample.humidity = 80", context);
  const warnings = vm.runInContext("vitalWarningsHtml(sample)", context);
  assert.match(warnings, /val-warning[^>]*>Akku \(Warnwert\): 25 %/);
  assert.match(warnings, /val-danger[^>]*>Spannung: 3\.20 V/);
  assert.match(warnings, /val-warning[^>]*>WLAN: -75 dBm/);
  assert.match(warnings, /val-danger[^>]*>Temperatur: 55\.0 °C/);
  assert.match(warnings, /val-warning[^>]*>Luftfeuchte: 80 % rF/);
  assert.doesNotMatch(warnings, /60 %|WLAN ·/);
  vm.runInContext("sample.battery_raw = null; sample.battery_percent = 15; sample.vbat = null; sample.rssi_dbm = null; sample.temp = null; sample.humidity = null", context);
  assert.match(vm.runInContext("vitalWarningsHtml(sample)", context), /val-danger[^>]*>Akku \(Warnwert\): 15 %/);
  vm.runInContext("sample.online = false", context);
  assert.equal(vm.runInContext("vitalWarningsHtml(sample)", context), "offline");
});

test("Taster card places escaped WLAN by MAC and leaves other vitals on their own row", () => {
  const { context, cards } = loadApp();
  vm.runInContext(`buttons = [{ id: "1", letter: "A", mac: "AA:BB", name: "Sensor",
    role: "none", online: true, ssid: "<test>", battery_percent: 80, rssi_dbm: -50 }];
    getSlotForButton = () => ({ slot: null }); renderButtonList();`, context);
  assert.equal(cards.length, 1);
  assert.match(cards[0].innerHTML, /taster-mac">Sensor · AA:BB · WLAN: &lt;test&gt;<\/div>/);
  assert.match(cards[0].innerHTML, /80%/);
  assert.equal((cards[0].innerHTML.match(/&lt;test&gt;/g) || []).length, 1);
});

test("Starter and Zieleinlauf show warnings and offline without healthy vitals", () => {
  const { context, elements } = loadApp();
  const box = () => ({ classList: { add() {}, remove() {} }, innerHTML: "" });
  elements.starterDrop = box();
  elements.finishDrop = box();
  vm.runInContext(`buttons = [
    { role: "starter", letter: "A", online: true, battery_percent: 80, temp: 25 },
    { role: "finish", letter: "B", online: false }
  ]; renderStarter(); renderFinishBox();`, context);
  assert.match(elements.starterDrop.innerHTML, /Taster A/);
  assert.doesNotMatch(elements.starterDrop.innerHTML, /80%|25\.0/);
  assert.match(elements.finishDrop.innerHTML, /offline/);
  vm.runInContext("buttons[0].temp = 46; renderStarter()", context);
  assert.match(elements.starterDrop.innerHTML, /Temperatur: 46\.0 °C/);
});

test("lane row stays compact unless a value exceeds a limit", () => {
  const { context, elements } = loadApp();
  const rows = [];
  elements.bahnenTableBody = { innerHTML: "", appendChild: row => rows.push(row) };
  elements.bahnenFooter = {};
  context.document.createElement = () => ({
    classList: { add() {} }, querySelector: () => ({ addEventListener() {} }),
  });
  vm.runInContext(`maxLane = 1; currentRun = 1;
    startcards = { rows: [{ Lauf: 1, Bahn: 1 }] };
    buttons = [{ id: "A", letter: "A", online: true, battery_percent: 80, temp: 25 }];
    laneAssignments = { 1: { active: "A", pending: null } };
    attachDropTargets = () => {}; updateClocks = () => {};
    renderLanesTable();`, context);
  assert.match(rows[0].innerHTML, /Taster A<\/strong><\/div>/);
  assert.doesNotMatch(rows[0].innerHTML, /80%|25\.0/);
  vm.runInContext("buttons[0].temp = 46; renderLanesTable()", context);
  assert.match(rows[1].innerHTML, /val-warning[^>]*>Temperatur: 46\.0 °C/);
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

test("vital chart bounds use fixed defaults and expand only beyond them", () => {
  const { context } = loadApp();
  for (const [index, inside, outside, expected] of [
    [2, [3.7, 4], [2.8, 4.3], [2.8, 4.3]],
    [3, [20, 30], [10, 45], [10, 45]],
    [5, [-80, -45], [-110, -20], [-110, -20]],
  ]) {
    context.index = index;
    context.values = inside;
    const bounds = vm.runInContext("vitalChartBounds(VITAL_CHARTS.find(c => c.idx === index), values)", context);
    const configured = vm.runInContext("VITAL_CHARTS.find(c => c.idx === index)", context);
    assert.deepEqual(Array.from(bounds), [configured.min, configured.max]);
    context.values = outside;
    assert.deepEqual(
      Array.from(vm.runInContext("vitalChartBounds(VITAL_CHARTS.find(c => c.idx === index), values)", context)),
      expected
    );
  }
  assert.deepEqual(
    Array.from(vm.runInContext("vitalChartBounds(CHARGER_CURRENT_CHART, [0.2, 8])", context)),
    [0, 10]
  );
  assert.deepEqual(
    Array.from(vm.runInContext("vitalChartBounds(CHARGER_CURRENT_CHART, [-1, 12])", context)),
    [-1, 12]
  );
});

test("sound switch saves immediately without altering other settings", async () => {
  const { context, elements } = loadApp();
  elements.tasterSoundsInput = { checked: false, disabled: false };
  elements.tasterSoundsStatus = {};
  vm.runInContext(`apiPost = async (path, body) => {
    if (path !== "/api/settings" || Object.keys(body).join() !== "taster_sounds" || body.taster_sounds !== false)
      throw new Error("incorrect setting request");
    if (!document.getElementById("tasterSoundsInput").disabled) throw new Error("not disabled");
  };
  apiGet = async () => ({taster_sounds: "0"});`, context);
  await vm.runInContext("updateTasterSounds(document.getElementById('tasterSoundsInput'))", context);
  assert.equal(elements.tasterSoundsInput.disabled, false);
  assert.equal(elements.tasterSoundsInput.checked, false);
});

test("rejected taster alert distinguishes pending and offline states and escapes names", () => {
  const { context, elements } = loadApp();
  const classes = {};
  elements.rejectedTasterAlert = {
    classList: { toggle: (name, state) => { classes[name] = state; } },
    textContent: "",
  };
  vm.runInContext(`renderRejectedTasters([
    {letter: "A", online: true, pending: true},
    {letter: "B", online: true, pending: false},
    {letter: "<C>", online: false, pending: false}
  ])`, context);
  assert.equal(classes["d-none"], false);
  assert.match(elements.rejectedTasterAlert.textContent, /A \(Druck noch im Puffer\)/);
  assert.match(elements.rejectedTasterAlert.textContent, /B \(Zustellung nicht mehr blockiert\)/);
  assert.match(elements.rejectedTasterAlert.textContent, /<C> \(offline – letzter Stand\)/);
  vm.runInContext("renderRejectedTasters([])", context);
  assert.equal(classes["d-none"], true);
});
