const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

test("Akkugrenzen werden geprüft und als Millivolt übertragen", () => {
  const inputs = {
    batteryZeroInput: { value: "3.30", checkValidity: () => true },
    batteryFullInput: { value: "4.00", checkValidity: () => true },
  };
  const context = vm.createContext({
    document: { getElementById: id => inputs[id] || { addEventListener() {} }, addEventListener() {} },
    localStorage: { getItem: () => null },
  });
  const source = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
  vm.runInContext(source, context);
  assert.equal(JSON.stringify(vm.runInContext("batterySettingsPayload()", context)),
    '{"battery_zero_mv":3300,"battery_full_mv":4000}');
  inputs.batteryZeroInput.value = "3.95";
  assert.throws(() => vm.runInContext("batterySettingsPayload()", context), /0,10 V/);
  inputs.batteryZeroInput.value = "";
  assert.throws(() => vm.runInContext("batterySettingsPayload()", context), /gültige Akkugrenzen/);
  inputs.batteryZeroInput.value = "3.331";
  inputs.batteryZeroInput.checkValidity = () => false;
  assert.throws(() => vm.runInContext("batterySettingsPayload()", context), /0,01-V/);
});
