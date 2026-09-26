import assert from "node:assert/strict";
import test from "node:test";
import { guestU64, mediaType, providerRequest } from "../../examples/provider-request.mjs";

const success = (payload, type = mediaType) => ({ value: { success: { mediaType: type, payload: Buffer.from(payload) } } });

test("provider results retain exact unsigned 64-bit values", () => {
  for (const value of ["0", "4", "2201", "18446744073709551615"]) {
    assert.equal(guestU64(success(JSON.stringify([value]))), value);
  }
});

test("provider results reject malformed values without weakening the success contract", () => {
  for (const payload of ['[]', '[4]', '["04"]', '["-1"]', '["18446744073709551616"]', '["4","4"]', '"4"']) {
    assert.throws(() => guestU64(success(payload)), /unexpected-guest-result/);
  }
  assert.throws(() => guestU64(success('["4"]', "text/plain")), /unexpected-guest-result/);
  assert.throws(() => guestU64(success(" ".repeat(129))), /unexpected-guest-result/);
  assert.throws(() => guestU64({ value: {} }), /unexpected-guest-result/);
});

test("platform failures keep their safe classification instead of becoming an unknown guest result", () => {
  for (const code of ["deadline-exceeded", "resource-exhausted", "permission-denied", "guest-trap", "unavailable", "internal"]) {
    assert.throws(() => guestU64({ value: { platformFailure: { code, message: "PRIVATE", detailItems: [{ kind: "PRIVATE" }] } } }),
      { message: `guest-platform-${code}` });
  }
});

test("unknown platform and declared errors never disclose server text", () => {
  for (const code of ["PRIVATE", "guest-trap\nPRIVATE", "x".repeat(1024), undefined, null, {}]) {
    assert.throws(() => guestU64({ value: { platformFailure: { code, message: "PRIVATE" } } }),
      { message: "guest-platform-unknown" });
  }
  assert.throws(() => guestU64({ value: { declaredError: { code: "PRIVATE", message: "PRIVATE" } } }),
    { message: "guest-declared-error" });
});

test("a failure cannot be hidden by an ambiguous success variant", () => {
  const response = success('["4"]');
  response.value.platformFailure = { code: "guest-trap" };
  assert.throws(() => guestU64(response), { message: "guest-platform-guest-trap" });
});

test("blob requests retain the finite provider budgets and input envelope", () => {
  const target = { service: "generic", route: "guest-blob", contract: "tests:local-blobs/api@1.0.0", function: "run" };
  const request = providerRequest(target, "tests", "typescript-blob", "blob", "http://localhost:1234/allowed");
  assert.deepEqual(JSON.parse(request.payload), [0, "http://localhost:1234/allowed", "0"]);
  assert.equal(request.budget.blobReadBytes, 65536n);
  assert.equal(request.budget.blobWriteBytes, 65536n);
  assert.equal(request.budget.wallTimeLimitMillis, 5000n);
  assert.equal(request.activationId, "typescript-blob");
});
