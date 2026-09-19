import assert from 'node:assert/strict';
import {contrast} from './palette.mjs';

export function cssHex(value) {
  if (/^#[0-9a-f]{6}$/i.test(value)) return value.toUpperCase();
  assert.match(value, /^rgba?\(/);
  const channels = value.match(/[\d.]+/g).map(Number);
  assert.ok(channels.length === 3 || channels[3] === 1, 'Expected an opaque computed theme color');
  return `#${channels.slice(0, 3).map(channel => Math.round(channel).toString(16).padStart(2, '0')).join('')}`.toUpperCase();
}

export function assertColorPair(foreground, background, minimum = 4.5) {
  const ratio = contrast(cssHex(foreground), cssHex(background));
  assert.ok(ratio >= minimum, `Computed color contrast: ${foreground}/${background} = ${ratio}`);
}

export async function textSamples(page, scope = 'body') {
  return page.evaluate(selector => {
    const root = document.querySelector(selector);
    if (!root) throw new Error('Missing contrast review root');
    function rgba(value) {
      const channels = value.match(/[\d.]+/g)?.map(Number);
      if (!channels || channels.length < 3) throw new Error(`Unsupported computed color: ${value}`);
      return [...channels.slice(0, 3), channels[3] ?? 1];
    }
    function blend(front, back) { return front.slice(0, 3).map((value, index) => value * front[3] + back[index] * (1 - front[3])); }
    function hex(channels) { return `#${channels.map(value => Math.round(value).toString(16).padStart(2, '0')).join('')}`; }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const samples = [];
    let node;
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim()) continue;
      const element = node.parentElement;
      if (!element || element.closest('svg, script, style, [aria-hidden="true"]') || !element.getClientRects().length) continue;
      const style = getComputedStyle(element);
      if (style.visibility !== 'visible') continue;
      const ancestors = [];
      for (let parent = element; parent; parent = parent.parentElement) ancestors.unshift(parent);
      let background = [255, 255, 255];
      let opacity = 1;
      for (const ancestor of ancestors) {
        const ancestorStyle = getComputedStyle(ancestor);
        background = blend(rgba(ancestorStyle.backgroundColor), background);
        opacity *= Number(ancestorStyle.opacity);
      }
      const foreground = rgba(style.color);
      foreground[3] *= opacity;
      samples.push({text: node.textContent.trim().slice(0, 70), foreground: hex(blend(foreground, background)), background: hex(background), tag: element.tagName});
      if (samples.length > 1500) throw new Error('Contrast review sample budget exceeded');
    }
    return samples;
  }, scope);
}

export function assertTextContrast(samples) {
  assert.ok(samples.length > 0, 'No rendered text sampled');
  const failures = samples.map(sample => ({...sample, ratio: contrast(sample.foreground, sample.background)})).filter(sample => sample.ratio < 4.5);
  assert.equal(failures.length, 0, `Rendered normal-text contrast failures: ${JSON.stringify(failures.slice(0, 12))}`);
  return {samples: samples.length, minimum: Math.min(...samples.map(sample => contrast(sample.foreground, sample.background)))};
}

export async function assertFocus(page) {
  const focus = await page.evaluate(() => {
    const element = document.activeElement;
    const rectangle = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const topmost = document.elementFromPoint(rectangle.left + rectangle.width / 2, rectangle.top + rectangle.height / 2);
    let parent = element.parentElement;
    while (parent?.parentElement && getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)') parent = parent.parentElement;
    return {label: element.textContent.slice(0, 60), visible: rectangle.width > 0 && rectangle.height > 0 && rectangle.top >= 0 && rectangle.bottom <= innerHeight + 1 && rectangle.left >= 0 && rectangle.right <= innerWidth + 1, unobscured: element === topmost || element.contains(topmost), outline: style.outlineStyle, width: Number.parseFloat(style.outlineWidth), color: style.outlineColor, background: getComputedStyle(parent).backgroundColor};
  });
  assert.ok(focus.visible && focus.unobscured && focus.outline !== 'none' && focus.width >= 3, `Missing/obscured keyboard focus: ${JSON.stringify(focus)}`);
  assertColorPair(focus.color, focus.background, 3);
}

export async function assertReflow(page) {
  const dimensions = await page.evaluate(() => ({content: document.documentElement.scrollWidth, viewport: innerWidth}));
  assert.ok(dimensions.content <= dimensions.viewport + 1, `Page-wide horizontal overflow: ${JSON.stringify(dimensions)}`);
}
