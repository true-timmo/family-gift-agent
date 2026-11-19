import assert from "node:assert/strict";
import { test } from "node:test";
import { PendingLoginStore } from "../src/pending-login.ts";

function memory() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => { data.set(k, v); },
    removeItem: (k: string) => { data.delete(k); },
  };
}

test("gemerkter Code bleibt bis zum Ablauf erhalten", () => {
  const store = memory();
  let now = 1000;
  const pending = new PendingLoginStore(() => store, () => now);
  pending.save({ name: "Mama", email: "m***@example.de", validUntil: 1600 });
  assert.deepEqual(new PendingLoginStore(() => store, () => now).load(),   // z.B. nach Neuladen
    { name: "Mama", email: "m***@example.de", validUntil: 1600 });
  now = 1600;
  assert.equal(pending.load(), null);
  assert.equal(store.getItem("geschenke.pendingLogin"), null);           // abgelaufen → vergessen
});

test("kaputte Daten oder gesperrter Speicher stören nicht", () => {
  const store = memory();
  store.setItem("geschenke.pendingLogin", "{kaputt");
  assert.equal(new PendingLoginStore(() => store).load(), null);
  const blocked = new PendingLoginStore(() => { throw new Error("SecurityError"); });
  blocked.save({ name: "Mama", email: "x", validUntil: 9e9 });
  assert.equal(blocked.load(), null);
});

test("Wartezeit für „Neuen Code schicken“", async () => {
  const { waitLabel } = await import("../src/views/login.templates.ts");
  assert.equal(waitLabel(1000, 1000), "");
  assert.equal(waitLabel(1042, 1000.2), "in 42 s");
  assert.equal(waitLabel(1000 + 600, 1000), "in 10 Min.");
});
