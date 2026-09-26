import assert from 'node:assert/strict';
import test from 'node:test';
import {assertControlContrast, controlSamples} from '../lib/control-review.mjs';

const border = (color = '#000000', width = 2, style = 'solid') => ({color, width, style});
const field = overrides => ({label: 'Review field', foreground: '#000000', background: '#FFFFFF', adjacent: '#FFFFFF', borders: Array.from({length: 4}, () => border()), ...overrides});

test('filled and outlined control identities meet their separate text and boundary budgets', () => {
  const samples = [field(), field({label: 'Filled', foreground: '#FFFFFF', background: '#000000', borders: []})];
  assert.deepEqual(assertControlContrast(samples), {samples: 2, minimumText: 21, minimumBoundary: 21});
});

test('readable labels cannot hide missing or low-contrast control boundaries', () => {
  for (const edge of [border('#FFFFFF'), border('#959595'), border('#000000', 0), border('#000000', 2, 'none'), border('#000000', 2, 'hidden')]) {
    assert.throws(() => assertControlContrast([field({borders: Array.from({length: 4}, () => edge)})]), /Control boundary contrast/);
  }
  assert.throws(() => assertControlContrast([field({borders: [border(), border(), border()]})]), /Missing control boundary/);
  assert.throws(() => assertControlContrast([field({borders: [border(), border(), border(), border('#FFFFFF')]})]), /Control boundary contrast/);
});

test('native value text is qualified even though it is not a DOM text node', () => {
  assert.throws(() => assertControlContrast([field({foreground: '#FFFFFF'})]), /Control text contrast/);
  assert.throws(() => assertControlContrast([field({foreground: '#GGGGGG'})]));
  assert.throws(() => assertControlContrast([field({background: 'rgba(255, 255, 255, 0.5)'})]), /opaque/);
});

test('empty and oversized control reviews fail closed', () => {
  assert.throws(() => assertControlContrast([]), /No rendered controls/);
  assert.throws(() => assertControlContrast(Array.from({length: 65}, () => field())), /budget/);
});

// DOM-shaped doubles exercise the exact evaluateAll callback; production tests
// additionally run rendered disappearing-border/value canaries in Chromium.
function element(style = {}, parentElement = null, options = {}) {
  return {
    style: {color: 'rgb(0, 0, 0)', backgroundColor: 'rgba(0, 0, 0, 0)', visibility: 'visible',
      opacity: '1', backgroundImage: 'none', filter: 'none', mixBlendMode: 'normal',
      backdropFilter: 'none', maskImage: 'none',
      ...Object.fromEntries(['Top', 'Right', 'Bottom', 'Left'].flatMap(side => [[`border${side}Width`, '2px'], [`border${side}Style`, 'solid'], [`border${side}Color`, 'rgb(0, 0, 0)']])), ...style},
    parentElement, tagName: 'INPUT', labels: [{textContent: 'Review field'}], textContent: '',
    getAttribute: () => null, getClientRects: () => options.hidden ? [] : [{}],
    matches: () => options.disabled === true,
  };
}

async function collect(elements) {
  const previous = globalThis.getComputedStyle;
  globalThis.getComputedStyle = element => element.style;
  try {
    return await controlSamples({locator: selector => {
      assert.equal(selector, 'fixture');
      return {evaluateAll: callback => callback(elements)};
    }}, 'fixture');
  } finally {
    if (previous === undefined) delete globalThis.getComputedStyle;
    else globalThis.getComputedStyle = previous;
  }
}

test('sampler resolves transparent wrappers and omits disabled or hidden specimens', async () => {
  const canvas = element({backgroundColor: 'rgb(255, 255, 255)'});
  const wrapper = element({}, canvas);
  const samples = await collect([element({}, wrapper), element({}, wrapper, {disabled: true}), element({}, wrapper, {hidden: true})]);
  assert.equal(samples.length, 1);
  assert.equal(samples[0].label, 'Review field');
  assert.equal(samples[0].background, 'rgb(255, 255, 255)');
  assert.equal(samples[0].adjacent, 'rgb(255, 255, 255)');
  assert.equal(assertControlContrast(samples).minimumBoundary, 21);
});

test('sampler refuses unsupported compositing and missing explicit backgrounds', async () => {
  for (const effect of [{opacity: '0.5'}, {backgroundImage: 'linear-gradient(black, white)'}, {filter: 'brightness(0.5)'}, {mixBlendMode: 'multiply'}, {backdropFilter: 'blur(2px)'}, {maskImage: 'url(mask.svg)'}]) {
    const canvas = element({backgroundColor: 'rgb(255, 255, 255)', ...effect});
    await assert.rejects(collect([element({}, canvas)]), /solid, uncomposited/);
  }
  await assert.rejects(collect([element()]), /explicit solid background/);
  await assert.rejects(collect(Array.from({length: 65}, () => element())), /budget/);
});
