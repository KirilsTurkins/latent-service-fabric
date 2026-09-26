import assert from 'node:assert/strict';
import test from 'node:test';
import {contrast} from '../lib/contrast.mjs';

test('shared sRGB contrast has exact endpoints and is symmetric', () => {
  assert.equal(contrast('#000000', '#FFFFFF'), 21);
  assert.equal(contrast('#FFFFFF', '#FFFFFF'), 1);
  assert.equal(contrast('#aabbcc', '#123456'), contrast('#123456', '#AABBCC'));
  assert.ok(contrast('#949494', '#FFFFFF') > 3);
  assert.ok(contrast('#959595', '#FFFFFF') < 3, 'Do not round a failing ratio up to 3:1');
});

test('invalid colors fail instead of producing a NaN contrast pass', () => {
  for (const value of ['#FFF', '#GGGGGG', '#FFFFFF00', 'FFFFFF', 'rgb(0,0,0)', '', null]) {
    assert.throws(() => contrast(value, '#FFFFFF'));
    assert.throws(() => contrast('#FFFFFF', value));
  }
});
