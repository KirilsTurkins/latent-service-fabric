import {randomUUID} from 'node:crypto';
import {eligible, equal, observe, requireValue, sameManifest} from './model.mjs';

function receiptMatches(receipt, row, attempt, intent) {
  return receipt?.formatVersion === 2 && receipt.operationId === attempt.id
    && receipt.tenant === intent.tenant && receipt.triggerId === row.desired.metadata.name
    && receipt.action === 'TRIGGER_OPERATION_ACTION_APPLY'
    && receipt.expectedGeneration === attempt.generation && receipt.expectedStateVersion === attempt.stateVersion
    && receipt.objectGeneration === receipt.stateVersion && BigInt(receipt.stateVersion) === BigInt(attempt.stateVersion) + 1n
    && receipt.target?.kind === 'static-web'
    && equal(receipt.target.publication, {id: intent.publication, tenant: intent.tenant});
}
function matchesCurrent(current, row, generation) {
  return current.generation === generation && (current.manifest === null ? row.baseline.manifest === null :
    sameManifest(current.manifest, row.desired));
}
function expected(row) { return row.attempts.findLast(attempt => attempt.status === 'confirmed')?.receipt.objectGeneration; }

export async function reconcile(client, journal, save, maximumWrites = 16) {
  let writes = 0, stage = journal.rows.some(row => row.attempts.some(attempt => attempt.status === 'pending')) ? 'uncertain' : 'failed';
  requireValue(Number.isInteger(maximumWrites) && maximumWrites >= 0 && maximumWrites <= 64, 'write-bound');
  const finish = async (status, reason, complete = false) => {
    journal.status = status; journal.reason = reason;
    await save(journal);
    return {schemaVersion: 'latent.static.route-result.v1', id: journal.id, status, reason,
      observedComplete: complete, writes, routes: journal.rows.map(row => ({id: row.desired.metadata.name,
        generation: expected(row) ?? null, pendingOperation: row.attempts.findLast(attempt => attempt.status === 'pending')?.id ?? null}))};
  };
  try {
    await eligible(client, journal.intent);
    for (const row of journal.rows) {
      const pending = row.attempts.findLast(attempt => attempt.status === 'pending');
      if (pending) {
        stage = 'uncertain';
        const result = await client.call(['trigger', 'operation', pending.id]);
        const current = await observe(client, row.desired.metadata.name, journal.intent.tenant);
        if (result.category !== 'success' || result.outcomeKnown !== true || result.data?.disposition !== 'found') {
          return finish('uncertain', 'receipt-unavailable-no-replay');
        }
        requireValue(receiptMatches(result.data.receipt, row, pending, journal.intent), 'receipt-identity-mismatch');
        pending.receipt = result.data.receipt; pending.status = 'confirmed';
        await save(journal);
        stage = 'failed';
        requireValue(matchesCurrent(current, row, result.data.receipt.objectGeneration), 'confirmed-route-changed-no-overwrite');
      }
      stage = 'failed';
      requireValue(!row.attempts.some(attempt => attempt.status === 'rejected' && attempt.code !== 'state-conflict'), 'previous-mutation-rejected-new-plan-required');
      let done = false;
      while (!done) {
        await eligible(client, journal.intent);
        const current = await observe(client, row.desired.metadata.name, journal.intent.tenant);
        const committed = expected(row);
        if (committed) {
          requireValue(matchesCurrent(current, row, committed), 'confirmed-route-changed-no-overwrite');
          done = true; continue;
        }
        requireValue(current.generation === row.baseline.generation && equal(current.manifest, row.baseline.manifest), 'route-changed-no-overwrite');
        if (current.manifest && sameManifest(current.manifest, row.desired)) { done = true; continue; }
        if (writes >= maximumWrites) return finish('partial', 'write-budget-reached');
        requireValue(row.attempts.length < 4, 'conflict-attempt-bound');
        const attempt = {id: 'route-' + randomUUID(), generation: current.generation, stateVersion: current.stateVersion, status: 'pending'};
        row.attempts.push(attempt);
        journal.status = 'applying'; await save(journal);
        stage = 'uncertain'; writes++;
        // This durable intent precedes the only dispatch. A timeout, truncated
        // response or process interruption leaves it pending for read-only recovery.
        const result = await client.apply(row.desired, attempt);
        if (result.category === 'success' && result.outcomeKnown === true) {
          requireValue(result.data?.durability === 'confirmed', 'mutation-durability-unconfirmed');
          requireValue(receiptMatches(result.data.receipt, row, attempt, journal.intent), 'receipt-identity-mismatch');
          attempt.receipt = result.data.receipt; attempt.status = 'confirmed'; await save(journal);
          stage = 'failed';
          continue;
        }
        if (result.outcomeKnown !== true) return finish('uncertain', 'mutation-outcome-unknown-no-replay');
        attempt.status = 'rejected'; attempt.code = result.error?.code ?? 'request-rejected'; await save(journal);
        stage = 'failed';
        requireValue(attempt.code === 'state-conflict', 'mutation-rejected');
        // Only a known rejection permits a fresh operation. The next live read
        // must still equal the original route generation and complete manifest.
      }
    }
    // Obtain one coherent route snapshot; unrelated writers can advance the
    // global fence, but they cannot change an owned route without detection.
    for (let scan = 0; scan < 3; scan++) {
      const versions = [];
      for (const row of journal.rows) {
        const current = await observe(client, row.desired.metadata.name, journal.intent.tenant);
        requireValue(matchesCurrent(current, row, expected(row) ?? row.baseline.generation), 'route-changed-no-overwrite');
        versions.push(current.stateVersion);
      }
      if (new Set(versions).size === 1) {
        await eligible(client, journal.intent);
        journal.observedStateVersion = versions[0];
        return finish('complete', 'current-route-set-observed', true);
      }
    }
    return finish('partial', 'catalog-changing-observation-incomplete');
  } catch (error) {
    const partial = journal.rows.some(row => expected(row));
    const reason = /^[a-z][a-z-]{0,95}$/.test(error.message) ? error.message : 'bounded-operation-failed';
    return finish(stage === 'uncertain' ? 'uncertain' : partial ? 'partial' : 'failed', reason);
  }
}
