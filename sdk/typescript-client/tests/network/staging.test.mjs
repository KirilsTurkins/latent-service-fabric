import test from "node:test";
import assert from "node:assert/strict";
import { encode, decode } from "../../dist/node/protocol/codec.js";
import { method } from "../../dist/node/protocol/schema.js";
import { validateResponse } from "../../dist/node/validation.js";

test("native staging witness keeps original unsigned proof and refuses malformed progress", () => {
  const original = () => ({
    schemaVersion: 1, retainedHistoryOnly: true, historyAvailable: true, page: {},
    nodes: [{
      activationId: "original", rootActivationId: "original", phase: "running", principalKind: "user", receivedAtUnixMillis: 1000n,
      grantedBudget: { effectCount: 2, stateWriteBytes: 18446744073709551615n },
      transactionStaging: {
        schemaVersion: 1, activationSerial: 18446744073709551615n, commandId: "1".repeat(64), attemptId: "2".repeat(64),
        transactionId: "3".repeat(64), publicationId: "publication:sha256:" + "4".repeat(64),
        stagedMutations: 2, capturedIntents: 2, stateWriteBytes: 18446744073709551615n, observedAtUnixMillis: 18446744073709551615n,
      },
    }],
  });
  const schema = method("inspectActivationTree").output;
  const roundtrip = value => decode(schema, encode(schema, value, 65536), 65536);
  const request = { activationId: "original" };
  const exact = roundtrip(original());
  validateResponse("inspectActivationTree", request, exact, "tenant");
  assert.equal(exact.nodes[0].transactionStaging.activationSerial, 18446744073709551615n);
  assert.equal(exact.nodes[0].transactionStaging.stateWriteBytes, 18446744073709551615n);
  const absent = original();
  delete absent.nodes[0].transactionStaging;
  assert.doesNotThrow(() => validateResponse("inspectActivationTree", request, roundtrip(absent), "tenant"));
  const malformed = [
    witness => { witness.schemaVersion = 2; }, witness => { witness.activationSerial = 0n; },
    witness => { witness.commandId = "A".repeat(64); }, witness => { witness.attemptId = "1"; },
    witness => { witness.transactionId += "0"; }, witness => { witness.publicationId = "4".repeat(64); },
    witness => { witness.stagedMutations = 129; }, witness => { witness.capturedIntents = 0; },
    witness => { witness.capturedIntents = 3; }, witness => { witness.stateWriteBytes = 0n; },
    witness => { witness.observedAtUnixMillis = 999n; },
  ];
  for (const change of malformed) {
    const value = original();
    change(value.nodes[0].transactionStaging);
    assert.throws(() => validateResponse("inspectActivationTree", request, roundtrip(value), "tenant"));
  }
  const noGrant = original();
  delete noGrant.nodes[0].grantedBudget;
  assert.throws(() => validateResponse("inspectActivationTree", request, roundtrip(noGrant), "tenant"));
});
