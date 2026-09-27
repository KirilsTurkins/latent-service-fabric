import assert from 'node:assert/strict';
import {test} from 'node:test';
import {capacity} from './catalog-capacity.mjs';

function fixture() {
  return {category: 'success', data: {inventory: {node: {id: 'test-node'}, observedAtUnixMillis: '1',
    topology: {available: true, entries: [{name: 'publication-catalog', attributes: {
      measurementStatus: 'available', chargedStorageBytes: '800', maximumStorageBytes: '1000',
      sharedBlobBytes: '200', publicationLinkBytes: '500', incompleteFileBytes: '100', webControlBytes: '0',
      contentIndexBytes: '10', maximumContentIndexBytes: '100', sharedBlobs: '3', maximumSharedBlobs: '100',
      indexedPublications: '9', maximumPublications: '10', releaseDirectories: '9', maximumRecoveryDirectories: '26',
      releaseIndexBytes: '10', maximumReleaseIndexBytes: '100', maximumFilesPerPublication: '1024',
    }}]}}}};
}

test('separate admission ceilings, exact remaining capacity and planning thresholds', () => {
  const report = capacity(fixture());
  assert.deepEqual(report.budgets[0], {name: 'storageBytes', used: '800', maximum: '1000', remaining: '200',
    utilizationBasisPoints: '8000', guidance: 'schedule-maintenance'});
  assert.equal(report.budgets[3].guidance, 'stop-promotion-and-maintain');
  assert.equal(report.physicalAllocatedBytes, null);
  assert.equal(report.retirementReclaimsCommittedBytes, false);
  assert.equal(report.observationReservesFutureAdmission, false);
});

test('unavailable or unsafe counters never become zero capacity observations', () => {
  for (const mutate of [
    value => { value.data.inventory.topology.available = false; },
    value => { value.data.inventory.topology.entries[0].attributes.measurementStatus = 'unavailable'; },
    value => { value.data.inventory.topology.entries[0].attributes.chargedStorageBytes = '799'; },
    value => { value.data.inventory.topology.entries[0].attributes.maximumStorageBytes = '0'; },
    value => { value.data.inventory.topology.entries[0].attributes.sharedBlobs = 3; },
    value => { value.data.inventory.topology.entries[0].attributes.sharedBlobs = '18446744073709551616'; },
    value => { value.data.inventory.topology.entries.push(value.data.inventory.topology.entries[0]); },
  ]) {
    const value = fixture(); mutate(value); assert.throws(() => capacity(value));
  }
});
