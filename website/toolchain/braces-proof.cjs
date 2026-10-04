'use strict';

// The scanner invokes this fixed harness with authenticated source packages,
// not a package manager, lifecycle script, or test code from a scan input.
const assert = require('node:assert/strict');
const path = require('node:path');
assert.equal(process.versions.node, '24.19.0');
assert.ok(process.execArgv.includes('--stack_size=512'));
assert.equal(process.argv.length, 4);
const original = require(path.join(process.argv[2], 'index.js'));
const derived = require(path.join(process.argv[3], 'index.js'));
assert.equal(require(path.join(process.argv[2], 'package.json')).version, '3.0.3');
assert.equal(require(path.join(process.argv[3], 'package.json')).version, '3.0.3+lsf-depth-v1');

// Observe the published vulnerability with a fixed stack before ordinary
// cases warm the recursive functions and change V8's overflow threshold.
const upstreamRegression = '('.repeat(4999) + 'x' + ')'.repeat(4999);
assert.ok(upstreamRegression.length < 10000);
assert.throws(() => original.compile(upstreamRegression), error => error instanceof RangeError &&
  /Maximum call stack size exceeded/.test(error.message));

let comparisons = 0;
let refusals = 0;
const outcome = callback => {
  try { return {value: callback()}; }
  catch (error) { return {error: [error.name, error.message]}; }
};
const compare = (left, right) => {
  assert.deepEqual(outcome(right), outcome(left));
  comparisons++;
};
// Include parser attributes and links, without losing cycles to JSON encoding.
const astIdentity = ast => {
  const ids = new Map([[ast, 0]]);
  const nodes = [ast];
  const result = [];
  for (let i = 0; i < nodes.length; i++) {
    const record = {};
    for (const [name, value] of Object.entries(nodes[i])) {
      if (name === 'parent' || name === 'prev') {
        if (!ids.has(value)) { ids.set(value, nodes.length); nodes.push(value); }
        record[name] = ids.get(value);
      } else if (name === 'nodes') {
        record[name] = value.map(node => {
          if (!ids.has(node)) { ids.set(node, nodes.length); nodes.push(node); }
          return ids.get(node);
        });
      } else {
        record[name] = value;
      }
    }
    result.push(record);
  }
  return result;
};

const patterns = [
  '', 'a', '{}', '{a,b}', 'foo/{a,b}/bar', 'foo/{a,b}/{c,d}', '{{a,b},{c,d}}',
  '{a,{b,c}}', 'a/{b,c}/d', '{1..10}', '{01..05}', '{-3..3}', '{5..1}',
  '{1..9..2}', '{a..f}', '{f..a}', '{a..z..3}', '{foo,bar,baz}', '{,a,,b,}',
  '${foo}', '${a,{b,c}}', 'a{b,c}d', 'a\\{b,c\\}d', '\\{x\\}',
  '[{a,b}]', '[a[b{c,d}]e]', '"{a,b}"', "'{a,b}'", '`{a,b}`', '"a\\"b"',
  'a(b{c,d})e', '({a,b})', 'a{b', '{a,b', '{a,b}}', '{a,b}c}',
  '{1..3,a}', '{1...3}', '{1..3..}', '{a,a,b}', '{,,}', '{a..a}',
  'Grüße/{München,Berlin}', '😀/{🌍,🌎}', 'x\u00a0y\ufeff{a,b}',
  'foo.{js,ts,jsx,tsx}', '**/*.{png,jpg}', '{src,test}/**/{a,b}.{js,ts}',
  '{' + '('.repeat(128) + 'x' + ')'.repeat(128) + '}',
];
// The last input deliberately crosses the fixed container limit. Ordinary
// comparisons stop at 128; security refusal is checked separately below.
patterns.pop();
for (const n of [1, 2, 8, 32, 64, 128]) {
  patterns.push('{'.repeat(n) + 'x' + '}'.repeat(n));
  patterns.push('('.repeat(n) + 'x' + ')'.repeat(n));
}
const options = [{}, {expand: true}, {keepQuotes: true}, {keepEscaping: true},
  {escapeInvalid: true}, {noempty: true}, {nodupes: true},
  {expand: true, noempty: true, nodupes: true}, {rangeLimit: 20},
  {maxLength: 10}, {maxLength: Infinity}, {rangeLimit: false}, {step: 2}];
for (const pattern of patterns) {
  for (const opts of options) {
    compare(() => original(pattern, opts), () => derived(pattern, opts));
    compare(() => original.create(pattern, opts), () => derived.create(pattern, opts));
    compare(() => astIdentity(original.parse(pattern, opts)), () => astIdentity(derived.parse(pattern, opts)));
    for (const api of ['compile', 'expand', 'stringify']) {
      compare(() => original[api](pattern, opts), () => derived[api](pattern, opts));
      compare(() => original[api](original.parse(pattern, opts), opts),
        () => derived[api](derived.parse(pattern, opts), opts));
    }
  }
}
for (const opts of options) {
  compare(() => original(['{a,b}', '{b,c}', '', 'foo'], opts),
    () => derived(['{a,b}', '{b,c}', '', 'foo'], opts));
}
for (const value of [null, 1, {}, undefined]) {
  compare(() => original.parse(value), () => derived.parse(value));
}
for (const api of ['compile', 'expand', 'stringify']) {
  compare(() => original[api](original.parse('foo/{a,b}/bar').nodes[2]),
    () => derived[api](derived.parse('foo/{a,b}/bar').nodes[2]));
}
compare(() => original('a'.repeat(10000)), () => derived('a'.repeat(10000)));
compare(() => original.parse('x'.repeat(10001)), () => derived.parse('x'.repeat(10001)));

const refuse = callback => {
  assert.throws(callback, error => error instanceof SyntaxError &&
    /^Brace AST nesting exceeds the fixed depth limit \(128\)$/.test(error.message));
  refusals++;
};
const attackPatterns = [
  '{'.repeat(129) + 'x' + '}'.repeat(129),
  '('.repeat(129) + 'x' + ')'.repeat(129),
  '({'.repeat(65) + 'x' + '})'.repeat(65),
  '{'.repeat(4096) + 'x' + '}'.repeat(4096),
  '('.repeat(4096) + 'x' + ')'.repeat(4096),
  '({'.repeat(2048) + 'x' + '})'.repeat(2048),
  '{'.repeat(4096), '('.repeat(4096),
];
for (const pattern of attackPatterns) {
  assert.ok(pattern.length < 10000);
  for (const opts of [{}, {maxLength: Infinity, maxDepth: Infinity, depthLimit: false, rangeLimit: false}]) {
    refuse(() => derived.parse(pattern, opts));
    for (const api of ['compile', 'expand', 'stringify', 'create']) {
      refuse(() => derived[api](pattern, opts));
    }
    refuse(() => derived(pattern, opts));
    refuse(() => derived(pattern, {...opts, expand: true}));
  }
}
// Establish the actual vulnerability on the same pinned runtime and original
// bytes. The observation is required; absence is not treated as remediation.
const deep = upstreamRegression;
for (const api of ['compile', 'expand', 'stringify']) {
  // A caller can bypass parse by supplying a deep, otherwise original AST.
  refuse(() => derived[api](original.parse(deep)));
  const root = {type: 'root', nodes: []};
  root.nodes.push(root);
  assert.throws(() => derived[api](root), error => error instanceof SyntaxError && /Cyclic/.test(error.message));
  refusals++;
  const forged = {type: 'paren', nodes: []};
  forged.parent = forged;
  assert.throws(() => derived[api](forged), error => error instanceof SyntaxError && /parent edge/.test(error.message));
  refusals++;
  const wide = {type: 'root', nodes: Array.from({length: 2 * 10000 + 4}, () => ({type: 'text', value: 'x'}))};
  assert.throws(() => derived[api](wide), error => error instanceof SyntaxError && /node limit/.test(error.message));
  refusals++;
  // Parent links outside the child traversal also consume the fixed bound.
  const detached = {type: 'root', nodes: []};
  for (let i = 0; i < 1000; i++) {
    let parent;
    for (let j = 0; j < 32; j++) { parent = {type: 'root', parent}; }
    detached.nodes.push({type: 'text', value: 'x', parent});
  }
  assert.throws(() => derived[api](detached), error => error instanceof SyntaxError && /node limit/.test(error.message));
  refusals++;
}
// Deep-looking quoted, escaped and bracket-literal input never enters the
// recursive AST containers and must retain upstream semantics.
for (const pattern of ['"' + deep + '"', "'" + deep + "'", '[' + deep + ']', '\\{'.repeat(4096)]) {
  compare(() => original(pattern), () => derived(pattern));
  compare(() => original.expand(pattern), () => derived.expand(pattern));
}
console.log(JSON.stringify({profile: 'braces-3.0.3-lsf-depth-v1', node: process.versions.node,
  status: 'pass', ordinary_api_comparisons: comparisons, malicious_refusals: refusals,
  upstream_stack_overflow_observed: true, max_depth: 128, max_ast_nodes: 2 * 10000 + 3}));
