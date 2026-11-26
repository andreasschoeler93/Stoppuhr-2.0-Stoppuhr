const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function setup() {
  const elements = {};
  for (const id of ["longtermMac", "longtermFrom", "longtermTo", "longtermShow",
    "longtermDownload", "longtermVitals", "longtermInfo", "longtermCharts"]) {
    elements[id] = {
      value: "", innerHTML: "", textContent: "", dataset: {},
      classList: { toggle() {} }, addEventListener() {},
    };
  }
  elements.longtermMac.value = "AA:BB:CC:DD:EE:FF";
  elements.longtermFrom.value = "2026-11-01";
  elements.longtermTo.value = "2026-11-07";
  const document = {
    getElementById: id => elements[id] || { addEventListener() {} },
    addEventListener() {},
  };
  const context = vm.createContext({ document, localStorage: { getItem: () => null, setItem() {} }, console });
  const app = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
  vm.runInContext(app, context);
  vm.runInContext("drawLongtermVitals_original = drawLongtermVitals", context);
  vm.runInContext("drawLongtermVitals = () => {}", context);
  return { context, elements };
}

test("selected MAC requests date range and shows saved minute points", async () => {
  const { context, elements } = setup();
  vm.runInContext(`apiGet = async url => {
    if (!url.startsWith("/api/vitals/longterm/AA%3ABB%3ACC%3ADD%3AEE%3AFF/points?from="))
      throw new Error("incorrect URL");
    return { fields: ["battery", "vbat", "temp", "humidity", "rssi"],
      points: [{ts: 1000, battery: 0, temp: 25}] };
  }`, context);
  await vm.runInContext("showLongtermVitals()", context);
  assert.match(elements.longtermVitals.textContent, /1 Minutenwerte/);
  assert.match(elements.longtermDownload.href, /AA%3ABB%3ACC%3ADD%3AEE%3AFF$/);
  assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(longtermData.series[0].points)", context)),
    [[1000, 0, null, 25, null, null]]);
});

test("longterm display loads every MAC as a toggleable series", async () => {
  const { context } = setup();
  vm.runInContext("drawLongtermVitals = () => {}", context);
  const requested = [];
  context.requested = requested;
  vm.runInContext(`
    longtermMacs = ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"];
    apiGet = async url => {
      requested.push(url);
      return { fields: ["battery"], points: [{ts: 1000, battery: url.includes("11%3A22") ? 50 : 25}] };
    };
  `, context);
  await vm.runInContext("showLongtermVitals()", context);
  assert.equal(requested.length, 2);
  assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(longtermData.series.map(s => s.label))", context)),
    ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]);
  assert.equal(vm.runInContext("longtermData.series[1].points[0][1]", context), 50);
});

test("longterm legend toggles individual MAC series", () => {
  const { context, elements } = setup();
  let click;
  elements.longtermInfo.addEventListener = (event, handler) => { click = handler; };
  vm.runInContext(`
    drawVitalChart = () => {};
    drawVitals = () => {};
    longtermData = { macs: ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"], t0: 0, t1: 1,
      series: [
        {label: "AA:BB:CC:DD:EE:FF", color: "blue", points: [[0, 10]]},
        {label: "11:22:33:44:55:66", color: "red", points: [[0, 20]]}
      ]};
    drawLongtermVitals_original();
  `, context);
  assert.match(elements.longtermInfo.innerHTML, /AA:BB:CC:DD:EE:FF/);
  assert.match(elements.longtermInfo.innerHTML, /11:22:33:44:55:66/);
  click({ target: { closest: () => ({ dataset: { series: "11:22:33:44:55:66" } }) } });
  assert.equal(vm.runInContext('hiddenSeries.has("11:22:33:44:55:66")', context), true);
});

test("invalid ranges and server failures are visible", async () => {
  const { context, elements } = setup();
  elements.longtermTo.value = "2027-01-01";
  await vm.runInContext("showLongtermVitals()", context);
  assert.match(elements.longtermVitals.textContent, /höchstens 31/);
  elements.longtermTo.value = "2026-11-07";
  vm.runInContext('apiGet = async () => { throw new Error("nicht erreichbar"); }', context);
  await vm.runInContext("showLongtermVitals()", context);
  assert.match(elements.longtermVitals.textContent, /nicht erreichbar/);
});

test("later selection wins when requests return out of order", async () => {
  const { context, elements } = setup();
  vm.runInContext(`var pending = []; apiGet = () => new Promise(resolve => pending.push(resolve));`, context);
  const first = vm.runInContext("showLongtermVitals()", context);
  elements.longtermMac.value = "11:22:33:44:55:66";
  const second = vm.runInContext("showLongtermVitals()", context);
  vm.runInContext('pending[1]({fields: [], points: [{ts: 2}]})', context);
  await second;
  vm.runInContext('pending[0]({fields: [], points: [{ts: 1}]})', context);
  await first;
  assert.equal(vm.runInContext("longtermData.series[0].label", context), "11:22:33:44:55:66");
});

test("longterm chart bridges missing minutes and does not include charger series", () => {
  const { context, elements } = setup();
  const operations = [];
  const g = {
    scale() {}, clearRect() {}, fillText() {}, fillRect() {}, beginPath() {}, stroke() {},
    setLineDash() {}, save() {}, restore() {},
    moveTo: (x, y) => operations.push(["move", x, y]),
    lineTo: (x, y) => operations.push(["line", x, y]),
  };
  elements["longterm-vc-3"] = { clientWidth: 400, clientHeight: 180, getContext: () => g };
  context.window = { devicePixelRatio: 1 };
  context.operations = operations;
  vm.runInContext(`
    chargerSeries = [{label:"charger", color:"red", points:[[0,null,null,99]]}];
    drawVitalChart(VITAL_CHARTS[2], [{label:"one",color:"blue",points:[
      [0,null,null,20], [60000,null,null,21], [120000,null,null,null], [180000,null,null,22]
    ]}], {canvasId:"longterm-vc-3",t0:0,t1:240000,longterm:true});
  `, context);
  const y22 = 8 + (1 - (22 - 15) / (40 - 15)) * (180 - 8 - 20);
  const x180 = 42 + (180000 / 240000) * (400 - 42 - 8);
  assert.ok(operations.some(([kind, x, y]) =>
    kind === "line" && x === x180 && Math.abs(y - y22) < 0.001));
  assert.ok(!operations.some(([, , y]) => y < -100));
});
