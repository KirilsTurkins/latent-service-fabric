#!/usr/bin/env node
// Reads an existing authenticated `latent node get --output json` receipt.
// It does not contact a node, traverse storage or mutate publications.
import assert from 'node:assert/strict';
import {open} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

const ceilings = [
  ['storageBytes', 'chargedStorageBytes', 'maximumStorageBytes'],
  ['contentIndexBytes', 'contentIndexBytes', 'maximumContentIndexBytes'],
  ['sharedBlobs', 'sharedBlobs', 'maximumSharedBlobs'],
  ['publications', 'indexedPublications', 'maximumPublications'],
  ['recoveryDirectories', 'releaseDirectories', 'maximumRecoveryDirectories'],
  ['releaseIndexBytes', 'releaseIndexBytes', 'maximumReleaseIndexBytes'],
];
const integer = value => {
  assert.equal(typeof value, 'string', 'decimal counter required');
  assert.match(value, /^(0|[1-9][0-9]{0,19})$/);
  const number = BigInt(value);
  assert.ok(number <= 18446744073709551615n, 'counter overflow');
  return number;
};

export function capacity(receipt) {
  assert.equal(receipt.category, 'success', 'successful authenticated inventory required');
  const inventory = receipt.data.inventory;
  assert.equal(inventory.topology.available, true, 'inventory unavailable');
  assert.ok(Array.isArray(inventory.topology.entries) && inventory.topology.entries.length <= 256);
  const entries = inventory.topology.entries.filter(row => row.name === 'publication-catalog');
  assert.equal(entries.length, 1, 'catalog observation missing or duplicated');
  const attributes = entries[0].attributes;
  assert.equal(attributes.measurementStatus, 'available', 'catalog observation unavailable; collect a fresh inventory');
  const budgets = ceilings.map(([name, usedKey, maximumKey]) => {
    const used = integer(attributes[usedKey]), maximum = integer(attributes[maximumKey]);
    assert.ok(maximum > 0n && used <= maximum, 'invalid catalog capacity');
    return {name, used: String(used), maximum: String(maximum), remaining: String(maximum - used),
      utilizationBasisPoints: String(used * 10000n / maximum),
      guidance: used * 10n >= maximum * 9n ? 'stop-promotion-and-maintain'
        : used * 5n >= maximum * 4n ? 'schedule-maintenance' : 'within-planning-threshold'};
  });
  const accounting = Object.fromEntries(['sharedBlobBytes', 'publicationLinkBytes', 'incompleteFileBytes', 'webControlBytes']
    .map(name => [name, String(integer(attributes[name]))]));
  assert.equal(Object.values(accounting).reduce((sum, value) => sum + BigInt(value), 0n),
    integer(attributes.chargedStorageBytes), 'inconsistent conservative storage accounting');
  return {schemaVersion: 'latent.publication.capacity.v1', node: inventory.node.id,
    observedAtUnixMillis: inventory.observedAtUnixMillis, budgets, accounting,
    maximumFilesPerPublication: String(integer(attributes.maximumFilesPerPublication)),
    physicalAllocatedBytes: null, physicalBytesMeasured: false,
    retirementReclaimsCommittedBytes: false, observationReservesFutureAdmission: false};
}

export async function main(args) {
  assert.equal(args.length, 1, 'usage: node tools/catalog-capacity.mjs INVENTORY.json');
  const handle = await open(args[0], 'r');
  try {
    const stat = await handle.stat();
    assert.ok(stat.isFile() && stat.size <= 1024 * 1024, 'regular inventory at most one MiB required');
    const buffer = Buffer.alloc(1024 * 1024 + 1);
    let bytes = 0;
    while (bytes < buffer.length) {
      const read = await handle.read(buffer, bytes, buffer.length - bytes, null);
      if (!read.bytesRead) break;
      bytes += read.bytesRead;
    }
    assert.ok(bytes <= 1024 * 1024, 'inventory byte ceiling');
    return capacity(JSON.parse(buffer.subarray(0, bytes).toString('utf8')));
  } finally { await handle.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { console.log(JSON.stringify(await main(process.argv.slice(2)), null, 2)); }
  catch { console.error('catalog-capacity: valid available bounded inventory required'); process.exitCode = 1; }
}
