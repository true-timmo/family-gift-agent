import assert from "node:assert/strict";
import { test } from "node:test";
import { biometricName, fromBase64url, toBase64url } from "../src/passkey.ts";

test("base64url hin und zurück (auch mit - und _ und ohne =)", () => {
  const bytes = new Uint8Array([0, 251, 255, 62, 63, 1, 2]);
  const text = toBase64url(bytes.buffer);
  assert.equal(text, "APv_Pj8BAg");
  assert.deepEqual(new Uint8Array(fromBase64url(text)), bytes);
});

test("Beschriftung passend zum Gerät", () => {
  assert.equal(biometricName("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X)"), "Face ID");
  assert.equal(biometricName("Mozilla/5.0 (Linux; Android 15; Pixel 9)"), "Fingerabdruck");
  assert.equal(biometricName("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)"), "Touch ID");
});
