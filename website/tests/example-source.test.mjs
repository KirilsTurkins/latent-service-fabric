import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {parseMetadata, readSchema} from '../plugins/examples/schema.mjs';
import {extractRegions} from '../plugins/examples/regions.mjs';

const root = new URL('../../', import.meta.url);
test('the actual Rust guest registration selects its maintained implementation, not a copied program', () => {
  const registry = parseMetadata(fs.readFileSync(new URL('examples/guides/registry.json', root), 'utf8'), readSchema('registry'));
  const registration = 'examples/guides/rust-echo/example.json';
  assert.ok(registry.scenarios.includes(registration));
  const scenario = parseMetadata(fs.readFileSync(new URL(registration, root), 'utf8'), readSchema('scenario'));
  assert.equal(scenario.id, 'guest/rust-echo'); assert.equal(scenario.target, 'guest');
  const [variant] = scenario.variants;
  assert.equal(variant.kind, 'maintained'); assert.equal(variant.language, 'rust');
  assert.equal(variant.validation.evidence, null, 'Do not invent matching runtime evidence');
  const regions = extractRegions(fs.readFileSync(new URL(variant.source, root), 'utf8'));
  assert.deepEqual(variant.regions, ['echo']);
  assert.match(regions.get('echo').code, /^impl Guest for EchoCapsule/);
  assert.match(regions.get('echo').code, /result\.map_err/);
});
