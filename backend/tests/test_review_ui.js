const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function element() {
  return {
    children: [],
    classList: { toggle() {} },
    style: {},
    value: "",
    handlers: {},
    append(...children) { this.children.push(...children); },
    replaceChildren() { this.children = []; },
    addEventListener(name, handler) { this.handlers[name] = handler; },
    get selectedOptions() { return this.children.filter(option => option.value === this.value); },
  };
}

function setup() {
  const elements = { unresolvedLaneAlerts: element(), unresolvedFinishAlerts: element() };
  const document = {
    createElement: element,
    getElementById: id => elements[id] || { addEventListener() {} },
    addEventListener() {},
  };
  const context = vm.createContext({
    document, confirm: () => true, alert() {}, localStorage: { getItem: () => null },
  });
  const source = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
  vm.runInContext(source, context);
  vm.runInContext(
    "apiPost = async (path, body) => { globalThis.posted = { path, body }; }; loadRunStatus = async () => {};",
    context
  );
  return { elements, context };
}

test("manual lane choices show durations and survive unchanged polling", async () => {
  const { elements, context } = setup();
  context.testPresses = [{
    id: "p", mac: "L1", ts: 15000, reason: "role_changed", original_lane: "1",
    candidates: [{ run_key: "5", time_ms: 5000, lanes: ["1"] }],
  }];
  vm.runInContext("renderUnresolvedLanes(testPresses)", context);
  const row = elements.unresolvedLaneAlerts.children[2];
  const select = row.children[1];
  assert.equal(select.children[1].textContent, "Lauf 5, Bahn 1: 5.00 s");
  select.value = select.children[1].value;
  row.children[2].value = "Startliste geprüft";
  vm.runInContext("renderUnresolvedLanes(testPresses)", context);
  assert.equal(elements.unresolvedLaneAlerts.children[2].children[1].value, select.value);
  assert.equal(elements.unresolvedLaneAlerts.children[2].children[2].value, "Startliste geprüft");
  await row.children[3].handlers.click();
  assert.equal(context.posted.path, "/api/lane-review/resolve");
  assert.equal(context.posted.body.action, "assign");
  assert.equal(context.posted.body.run_key, "5");
  assert.equal(context.posted.body.lane, "1");
});

test("unvalued lane decision requires a reason", async () => {
  const { elements, context } = setup();
  context.testPresses = [{ id: "p", mac: "L1", ts: 15000, reason: "role_changed", candidates: [] }];
  vm.runInContext("renderUnresolvedLanes(testPresses)", context);
  const row = elements.unresolvedLaneAlerts.children[2];
  await row.children[4].handlers.click();
  assert.equal(context.posted, undefined);
  row.children[2].value = "Kampfrichterprotokoll";
  await row.children[4].handlers.click();
  assert.equal(context.posted.body.action, "park");
  assert.equal(context.posted.body.run_key, null);
});

test("finish duplicate is available only for identical recorded events", async () => {
  const { elements, context } = setup();
  context.testPresses = [{
    id: "p", mac: "FIN", ts: 15000,
    candidates: [{ run_key: "5", time_ms: 5000, duplicate: true },
                 { run_key: "6", time_ms: 3000, duplicate: false }],
  }];
  vm.runInContext("renderUnresolvedFinish(testPresses)", context);
  const row = elements.unresolvedFinishAlerts.children[2];
  const select = row.children[1];
  const duplicate = row.children[3];
  assert.equal(duplicate.disabled, true);
  select.value = "5";
  select.handlers.change();
  assert.equal(duplicate.disabled, false);
  await duplicate.handlers.click();
  assert.equal(context.posted.body.action, "duplicate");
  select.value = "6";
  select.handlers.change();
  assert.equal(duplicate.disabled, true);
});
