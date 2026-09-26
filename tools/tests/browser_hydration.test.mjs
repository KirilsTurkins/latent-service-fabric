import {test} from 'node:test';
import assert from 'node:assert/strict';
import {MAX_HYDRATION_BYTES, projectHydration, serializeHydration, parseHydration} from '../../examples/browser-boundary/shared/hydration.ts';

test('canonical raw-text JSON escapes breakout, entities and Unicode separators', () => {
  const input = '</ScRiPt><script>globalThis.breakout=true</script>&><\u2028\u2029';
  const encoded = serializeHydration({displayName: input});
  assert.doesNotMatch(encoded, /[<>&\u2028\u2029]/);
  assert.equal(parseHydration(encoded).displayName, input);
  assert.equal(Object.getPrototypeOf(parseHydration(encoded)), null);
  assert.ok(Object.isFrozen(parseHydration(encoded)));
});

test('projection copies only explicit primitive DTO fields without observing secret accessors', () => {
  let observed = false;
  const source = {displayName: 'public', credential: 'Bearer never-transfer', serverOnly: new Date(),
    get secret() { observed = true; throw new Error('secret touched'); }};
  const selected = projectHydration(source, ['displayName']);
  assert.equal(serializeHydration(selected), '{"displayName":"public"}');
  assert.equal(observed, false);
  assert.throws(() => projectHydration(source, ['serverOnly']), /hydration-scalar/);
  assert.throws(() => projectHydration(source, ['secret']), /hydration-accessor/);
  assert.equal(observed, false);
});

test('objects, executable hooks, prototype keys, symbols and ambiguous JSON fail closed', () => {
  for (const value of [[], new Date(), {nested: {}}, {nested: []}, {callback: () => 1},
    {number: NaN}, {number: Infinity}, {number: -0}, {missing: undefined}, {value: 1n},
    {constructor: 'bad'}, JSON.parse('{"__proto__":"bad"}'), {toJSON() { throw new Error('executed'); }}]) {
    assert.throws(() => serializeHydration(value), /hydration-/);
  }
  let observed = false;
  assert.throws(() => serializeHydration({get displayName() { observed = true; return 'bad'; }}), /hydration-accessor/);
  assert.equal(observed, false);
  assert.throws(() => serializeHydration({[Symbol('secret')]: 1}), /hydration-fields/);
  for (const value of ['{"name":"one","name":"two"}', '{ "name": "one" }', '{"name":"<"}']) {
    assert.throws(() => parseHydration(value), /hydration-noncanonical/);
  }
});

test('field, scalar and escaped UTF-8 ceilings reject before a transferable result exists', () => {
  assert.throws(() => serializeHydration({name: 'x'.repeat(8193)}), /hydration-scalar/);
  assert.throws(() => serializeHydration({name: '<'.repeat(8192)}), /hydration-size/);
  assert.throws(() => serializeHydration(Object.fromEntries(Array.from({length:65}, (_, index) => ['key' + index, 1]))), /hydration-fields/);
  assert.throws(() => projectHydration({name:'one'}, ['name', 'name']), /hydration-fields/);
  assert.throws(() => parseHydration(' '.repeat(MAX_HYDRATION_BYTES + 1)), /hydration-size/);
  const exact = {a:'x'.repeat(8192), b:'x'.repeat(8192), c:'x'.repeat(8192), d:'x'.repeat(8163)};
  assert.equal(Buffer.byteLength(serializeHydration(exact)), MAX_HYDRATION_BYTES);
  assert.throws(() => serializeHydration({...exact, d: exact.d + 'x'}), /hydration-size/);
});
