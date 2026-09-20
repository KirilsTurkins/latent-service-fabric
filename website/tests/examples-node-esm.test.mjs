import assert from 'node:assert/strict';
import test from 'node:test';
import {fixture} from './example-fixtures.mjs';
import {extractExamples} from '../plugins/examples/extract.mjs';

test('a registered Node ESM client is read as source and never executed', t => {
  const f = fixture(t, ['typescript']);
  const variant = f.scenario.variants[0];
  const previous = variant.source;
  variant.source = 'sdk/fixture/example.mjs';
  f.write(variant.source, 'throw new Error("MUST NOT EXECUTE");\n' + f.read(previous));
  f.save(); f.commit();
  const result = extractExamples(f.root, f.requests, f.identity());
  const displayed = result.bundle.examples[0].regions[0].variants[0];
  assert.equal(displayed.environment, 'node');
  assert.equal(displayed.language, 'typescript');
  assert.match(displayed.snippet.code, /const value/);
  assert.doesNotMatch(displayed.snippet.code, /MUST NOT EXECUTE/);
  variant.language = 'rust'; f.save(); f.commit();
  assert.throws(() => extractExamples(f.root, f.requests, f.identity()), /language\/source type mismatch/);
});
