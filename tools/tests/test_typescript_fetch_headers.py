"""Standard header controls only; no signed fetch/provider qualification."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TypeScriptFetchHeadersTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_normalization_iteration_and_mutation_match_native_headers(self):
        script = r"""
import assert from 'node:assert/strict';
import {Headers as Candidate} from './headers.mjs';
const Native = globalThis.Headers;
const initial = [['B', ' two\t'], ['A', '\tfirst '], ['a', 'second'],
  ['Set-Cookie', 'a=b'], ['Set-Cookie', 'c=d']];
const actual = new Candidate(initial);
const expected = new Native(initial);
function compare() {
  assert.deepEqual([...actual], [...expected]);
  assert.deepEqual([...actual.keys()], [...expected.keys()]);
  assert.deepEqual([...actual.values()], [...expected.values()]);
  assert.deepEqual(actual.getSetCookie(), expected.getSetCookie());
  for (const key of ['a', 'b', 'A', 'SET-cookie', 'missing']) {
    assert.equal(actual.has(key), expected.has(key));
    assert.equal(actual.get(key), expected.get(key));
  }
}
compare();
for (const [method, args] of [['append', ['A', ' third']], ['set', ['B', 'new']],
  ['delete', ['a']], ['set', ['set-cookie', 'fresh=value']]]) {
  actual[method](...args);
  expected[method](...args);
  compare();
}
assert.deepEqual([...new Candidate(actual)], [...expected]);
assert.deepEqual([...new Candidate({Z: 4, a: false})], [...new Native({Z: 4, a: false})]);
const seen = [];
const receiver = {};
actual.forEach(function (value, key, owner) {
  assert.equal(this, receiver);
  assert.equal(owner, actual);
  seen.push([key, value]);
}, receiver);
assert.deepEqual(seen, [...expected]);
assert.equal(Object.prototype.toString.call(actual), '[object Headers]');
for (const init of [null, [['a']], [['a', 'b', 'c']], [['bad name', 'value']],
  [['good', 'bad\nvalue']], [['good', '\u0100']]]) {
  assert.throws(() => new Candidate(init), TypeError);
  assert.throws(() => new Native(init), TypeError);
}
const original = {original: true};
assert.throws(() => actual.append({toString() { throw original; }}, 'x'),
  error => error === original);
"""
        self.run_node(script)

    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_profile_limits_and_response_guard_retain_existing_values(self):
        script = r"""
import assert from 'node:assert/strict';
import {Headers} from './headers.mjs';
const actual = new Headers([['original', 'value']]);
const before = Headers.typed(actual);
assert.throws(() => actual.append('oversize', 'x'.repeat(32769)), TypeError);
assert.deepEqual(Headers.typed(actual), before);
assert.throws(() => actual.set('original', 'x'.repeat(32769)), TypeError);
assert.deepEqual(Headers.typed(actual), before);
const maximum = new Headers(Array.from({length: 128}, (_, i) => [`x-${i}`, 'v']));
assert.throws(() => maximum.append('extra', 'v'), TypeError);
assert.equal([...maximum].length, 128);
assert.throws(() => new Headers(Array.from({length: 129}, () => ['x', 'v'])), TypeError);
const response = Headers.fromTyped([{name: 'content-type', value: 'application/json'}]);
for (const [method, args] of [['set', ['a', 'b']], ['append', ['a', 'b']], ['delete', ['content-type']]]) {
  assert.throws(() => response[method](...args), TypeError);
}
assert.equal(response.get('content-type'), 'application/json');
assert.deepEqual(Headers.typed(response), [{name: 'content-type', value: 'application/json'}]);
assert.throws(() => Headers.typed({}), TypeError);
"""
        self.run_node(script)

    def run_node(self, script):
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            (root / "headers.mjs").write_bytes(
                (ROOT / "sdk/typescript-guest/runtime/http-headers.mjs").read_bytes()
            )
            (root / "test.mjs").write_text(script, encoding="utf-8")
            result = subprocess.run(
                [shutil.which("node"), str(root / "test.mjs")],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
