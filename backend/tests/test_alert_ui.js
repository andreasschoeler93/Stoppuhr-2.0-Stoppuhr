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

test("red and yellow messages both show a mute button", () => {
  const c = setup();
  const red = vm.runInContext('alertBannerHtml("danger", "<Warnung>")', c);
  const yellow = vm.runInContext('alertBannerHtml("warning", "Hinweis")', c);
  assert.match(red, /&lt;Warnung&gt;/);
  assert.match(red, /alert-mute/);
  assert.match(yellow, /alert-mute/);
});

test("mute sends the selected warning level and displays an error on failure", async () => {
  const c = setup();
  const banner = {
    classList: { contains: level => level === "alert-warning" },
    querySelector: () => ({ textContent: "Taster I: Akku auffällig (30 %)." }),
  };
  const button = {
    disabled: false,
    closest: () => banner,
  };
  c.event = { target: { closest: () => button } };
  vm.runInContext(`var sent = []; apiPost = async (url, body) => { sent.push({url, body}); };
    reportAlerts = async () => {};`, c);
  await vm.runInContext("muteAlert(event)", c);
  assert.equal(vm.runInContext("sent[0].url", c), "/api/alert-state/mute");
  assert.equal(vm.runInContext("sent[0].body.alert", c), "Taster I: Akku auffällig (30 %).");
  assert.equal(vm.runInContext("sent[0].body.level", c), "warning");
  vm.runInContext(`apiPost = async () => { throw new Error("offline"); };
    var errorMessage = ""; alert = message => { errorMessage = message; };`, c);
  await vm.runInContext("muteAlert(event)", c);
  assert.equal(button.disabled, false);
  assert.match(vm.runInContext("errorMessage", c), /offline/);
});
