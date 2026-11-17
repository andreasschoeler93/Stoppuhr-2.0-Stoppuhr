const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function setup() {
  const messages = [];
  const calls = [];
  const detail = { cleared: false, addEventListener() {}, replaceChildren() { this.cleared = true; } };
  const context = vm.createContext({
    document: { addEventListener() {}, getElementById: () => detail },
    localStorage: { getItem: () => null },
    window: { confirm: question => { messages.push(question); return true; } },
    alert: message => messages.push(message),
    location: {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8"), context);
  context.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  };
  vm.runInContext("refreshArchive = async () => { globalThis.refreshed = true; };", context);
  return { context, messages, calls, detail };
}

test("deletion requires confirmation and only sends selected ids", async () => {
  const { context, messages, calls, detail } = setup();
  context.items = [{ id: "1", name: "Erster" }, { id: "2", name: "Zweiter" }];
  vm.runInContext('openArchiveId = "1"', context);
  await vm.runInContext("deleteArchives(items)", context);
  assert.match(messages[0], /Erster \(ID 1\)/);
  assert.match(messages[0], /Zweiter \(ID 2\)/);
  assert.match(messages[0], /laufende Wettkampf bleibt erhalten/);
  assert.deepEqual(calls.map(c => c.url), ["/api/archive/1", "/api/archive/2"]);
  assert.ok(calls.every(c => c.options.method === "DELETE"));
  assert.equal(detail.cleared, true);
  assert.equal(context.refreshed, true);
});

test("cancelling never deletes an archive", async () => {
  const { context, calls } = setup();
  context.window.confirm = () => false;
  context.items = [{ id: "1", name: "Erster" }];
  await vm.runInContext("deleteArchives(items)", context);
  assert.equal(calls.length, 0);
  assert.equal(context.refreshed, undefined);
});

test("partial errors are reported and only confirmed deleted details are cleared", async () => {
  const { context, messages, detail } = setup();
  context.items = [{ id: "1", name: "Erster" }, { id: "2", name: "Zweiter" }];
  context.fetch = async url => url.endsWith("/1")
    ? { ok: true, status: 200, json: async () => ({ ok: true }) }
    : { ok: false, status: 503, json: async () => ({ ok: false, error: "Redis nicht erreichbar" }) };
  vm.runInContext('openArchiveId = "2"', context);
  await vm.runInContext("deleteArchives(items)", context);
  assert.equal(detail.cleared, false);
  assert.equal(context.refreshed, true);
  assert.match(messages[1], /1 von 2 Löschungen bestätigt/);
  assert.match(messages[1], /Zweiter.*Redis nicht erreichbar/);
});

test("archive selection and single delete controls use the same confirmation flow", async () => {
  const { context } = setup();
  const handler = () => ({ handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; } });
  const select1 = Object.assign(handler(), { checked: true, dataset: { archSelect: "1" } });
  const select2 = Object.assign(handler(), { checked: false, dataset: { archSelect: "2" } });
  const single = Object.assign(handler(), { dataset: { archDel: "2" } });
  const button = handler();
  const box = {
    querySelectorAll(selector) {
      return {
        "[data-arch-open]": [], "[data-arch-del]": [single],
        "[data-arch-select]": [select1, select2], "button, input": [select1, select2, single, button],
      }[selector];
    },
  };
  context.document.getElementById = id => id === "archiveList" ? box : button;
  vm.runInContext(`apiGet = async () => ({items: [{id:"1",name:"A"},{id:"2",name:"B"}]});
    deleteArchives = async items => { globalThis.selected = items.map(i => i.id); };`, context);
  const source = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
  vm.runInContext(source.slice(source.indexOf("async function refreshArchive()"), source.indexOf("async function openArchive(")), context);
  await vm.runInContext("refreshArchive()", context);
  select1.handlers.change();
  assert.equal(button.disabled, false);
  await button.handlers.click();
  assert.equal(JSON.stringify(context.selected), '["1"]');
  await single.handlers.click();
  assert.equal(JSON.stringify(context.selected), '["2"]');
});
