import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {approvedPairs, contrast, loadPalette, mermaidOptions, paletteCss, prismTheme, syntaxTokens, validatePalette} from '../lib/palette.mjs';
import {websiteRoot} from '../lib/repository.mjs';

test('semantic palette covers both modes and every approved text/control pairing', () => {
  const palette = loadPalette();
  const results = validatePalette(palette);
  assert.equal(results.length, approvedPairs().length * 2);
  assert.equal(Object.keys(palette.modes.light).length, 40);
  assert.equal(contrast('#000000', '#FFFFFF'), 21);
  assert.equal(contrast('#FFFFFF', '#FFFFFF'), 1);
  assert.equal(contrast('#FFFFFF', '#000000'), 21);
});

test('schema and contrast fail closed on missing, extra, opaque or unreadable tokens', () => {
  for (const mutation of [
    palette => delete palette.modes.dark.focus,
    palette => palette.modes.light.unreviewed = '#000000',
    palette => palette.modes.light.text = 'rgba(0,0,0,0.2)',
    palette => palette.modes.light.link = palette.modes.light.canvas,
    palette => palette.modes.dark.codeComment = palette.modes.dark.codeSurface,
    palette => palette.modes.dark.successBorder = palette.modes.dark.successSurface,
    palette => delete palette.modes.dark,
  ]) {
    const candidate = structuredClone(loadPalette());
    mutation(candidate);
    assert.throws(() => validatePalette(candidate), /palette|</);
  }
});

test('generated CSS and Prism derive from the same tokens without independent colors', () => {
  const palette = loadPalette();
  assert.equal(paletteCss(palette), paletteCss(structuredClone(palette)));
  for (const tokens of Object.values(palette.modes)) {
    for (const value of Object.values(tokens)) assert.ok(paletteCss(palette).includes(value));
    const prism = prismTheme(tokens);
    assert.equal(prism.plain.color, tokens.codeText);
    assert.equal(prism.plain.backgroundColor, tokens.codeSurface);
    for (const token of syntaxTokens.slice(1)) assert.ok(prism.styles.some(rule => rule.style.color === tokens[`code${token}`]));
  }
  for (const stylesheet of ['foundation.css', 'theme.css']) {
    assert.doesNotMatch(fs.readFileSync(path.join(websiteRoot, 'src/css', stylesheet), 'utf8'), /#[\da-f]{3,8}\b|\brgba?\(|\bhsla?\(/i);
  }
  const changed = structuredClone(palette);
  changed.modes.dark.accent = '#F2CA68';
  assert.notEqual(paletteCss(changed), paletteCss(palette));
  assert.equal(mermaidOptions(palette.modes.dark).themeVariables.primaryTextColor, palette.modes.dark.text);
  assert.equal(mermaidOptions(palette.modes.dark).htmlLabels, false);
});
