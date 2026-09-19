import assert from 'node:assert/strict';
import test from 'node:test';
import {assertColorPair, assertTextContrast, cssHex} from '../lib/theme-review.mjs';

test('rendered contrast assertions reject invisible text and unsupported alpha', () => {
  assert.equal(cssHex('rgb(255, 255, 255)'), '#FFFFFF');
  assert.equal(cssHex('rgba(0, 0, 0, 1)'), '#000000');
  assert.throws(() => cssHex('rgba(0, 0, 0, 0.4)'), /opaque/);
  assert.throws(() => assertTextContrast([]), /No rendered/);
  assert.throws(() => assertTextContrast([{text: 'canary', foreground: '#FFFFFF', background: '#FFFFFF'}]), /contrast/);
  assertColorPair('rgb(0, 0, 0)', 'rgb(255, 255, 255)');
  assert.throws(() => assertColorPair('rgb(0, 0, 0)', 'rgb(0, 0, 0)', 3), /contrast/);
});
