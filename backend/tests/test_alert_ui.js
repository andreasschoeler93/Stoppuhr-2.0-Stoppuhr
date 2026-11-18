const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function setup() {
  const document = { getElementById: () => ({ addEventListener() {} }), addEventListener() {} };
  const context = vm.createContext({ document, localStorage: { getItem: () => null }, console });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8"), context);
  return context;
}

test("red messages show mute button, yellow messages do not", () => {
  const c = setup();
  const red = vm.runInContext('alertBannerHtml("danger", "<Warnung>")', c);
  assert.match(red, /&lt;Warnung&gt;/);
  assert.match(red, /alert-mute/);
  assert.doesNotMatch(vm.runInContext('alertBannerHtml("warning", "Warnung")', c), /alert-mute/);
});

test("mute sends only selected text and displays an error on failure", async () => {
  const c = setup();
  const button = {
    disabled: false,
    closest: () => ({ querySelector: () => ({ textContent: "Taster I: Akku kritisch (4 %)." }) }),
  };
  c.event = { target: { closest: () => button } };
  vm.runInContext(`var sent = []; apiPost = async (url, body) => { sent.push({url, body}); };
    reportAlerts = async () => {};`, c);
  await vm.runInContext("muteAlert(event)", c);
  assert.equal(vm.runInContext("sent[0].url", c), "/api/alert-state/mute");
  assert.equal(vm.runInContext("sent[0].body.alert", c), "Taster I: Akku kritisch (4 %).");
  vm.runInContext(`apiPost = async () => { throw new Error("offline"); };
    var errorMessage = ""; alert = message => { errorMessage = message; };`, c);
  await vm.runInContext("muteAlert(event)", c);
  assert.equal(button.disabled, false);
  assert.match(vm.runInContext("errorMessage", c), /offline/);
});
