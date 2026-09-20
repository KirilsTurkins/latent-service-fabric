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

test('computed colors reject malformed, extra and out-of-range channels', () => {
  for (const value of ['rgb(-1, 0, 0)', 'rgb(256, 0, 0)', 'rgb(0, 0)',
    'rgb(0, 0, 0, 1)', 'rgba(0, 0, 0)', 'rgba(0, 0, 0, 1, 2)',
    'rgb(0, 0, 0) trailing', 'rgb(0%, 0%, 0%)', 'rgba(0, 0, 0, 1.1)']) {
    assert.throws(() => cssHex(value), /computed|opaque|channel/);
  }
  assert.equal(cssHex('#aabbcc'), '#AABBCC');
  assert.equal(cssHex('rgb(12.4, 100.5, 255)'), '#0C65FF');
});

test('evidence records the running host rather than a fixed review platform', async () => {
  const os = await import('node:os');
  const {reviewEnvironment} = await import('../lib/theme-review.mjs');
  assert.deepEqual(reviewEnvironment(), {
    platform: process.platform, architecture: process.arch,
    osRelease: os.release(), node: process.version,
  });
});
