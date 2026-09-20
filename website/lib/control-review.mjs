import assert from 'node:assert/strict';
import {contrast} from './contrast.mjs';
import {cssHex} from './theme-review.mjs';

// This bounded review covers solid, author-styled controls. Native checkbox
// glyphs, platform popups and image-backed controls still need human review.
export async function controlSamples(page, selector) {
  return page.locator(selector).evaluateAll(elements => {
    if (elements.length > 64) throw new Error('Control review sample budget exceeded');
    function background(element) {
      for (let parent = element; parent; parent = parent.parentElement) {
        const color = getComputedStyle(parent).backgroundColor;
        if (color !== 'rgba(0, 0, 0, 0)') return color;
      }
      throw new Error('Control review requires an explicit solid background');
    }
    return elements.filter(element => element.getClientRects().length
      && getComputedStyle(element).visibility === 'visible'
      && !element.matches(':disabled, [aria-disabled="true"]')).map(element => {
      // Do not silently certify colors that a compositor can change. Current
      // theme controls are opaque and have no gradients, masks or filters.
      for (let parent = element; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (style.opacity !== '1' || style.backgroundImage !== 'none'
          || style.filter !== 'none' || style.mixBlendMode !== 'normal'
          || (style.backdropFilter || 'none') !== 'none'
          || (style.maskImage || 'none') !== 'none') {
          throw new Error('Control review requires solid, uncomposited colors');
        }
      }
      const style = getComputedStyle(element);
      return {
        label: (element.getAttribute('aria-label') || element.labels?.[0]?.textContent || element.textContent || element.tagName).trim().slice(0, 80),
        foreground: style.color,
        background: background(element),
        adjacent: background(element.parentElement),
        borders: ['Top', 'Right', 'Bottom', 'Left'].map(side => ({
          width: Number.parseFloat(style[`border${side}Width`]),
          style: style[`border${side}Style`], color: style[`border${side}Color`],
        })),
      };
    });
  });
}

export function assertControlContrast(samples) {
  assert.ok(samples.length > 0 && samples.length <= 64, 'No rendered controls sampled or control review budget exceeded');
  const results = samples.map(sample => {
    const background = cssHex(sample.background);
    const adjacent = cssHex(sample.adjacent);
    // TreeWalker does not see the value text of native input/select controls.
    const text = contrast(cssHex(sample.foreground), background);
    assert.ok(text >= 4.5, `Control text contrast: ${sample.label} = ${text}`);
    const fill = contrast(background, adjacent);
    let boundary = fill;
    if (fill < 3) {
      assert.equal(sample.borders.length, 4, `Missing control boundary: ${sample.label}`);
      const borders = sample.borders.map(border => {
        if (!(border.width > 0) || border.style === 'none' || border.style === 'hidden') return 1;
        return contrast(cssHex(border.color), adjacent);
      });
      boundary = Math.min(...borders);
    }
    assert.ok(boundary >= 3, `Control boundary contrast: ${sample.label} = ${boundary}`);
    return {text, boundary};
  });
  return {samples: results.length, minimumText: Math.min(...results.map(result => result.text)), minimumBoundary: Math.min(...results.map(result => result.boundary))};
}
