import fs from 'node:fs';
import path from 'node:path';
import Ajv from 'ajv';
import {readSource, repositoryRoot, requireValue, sha256, websiteRoot} from './repository.mjs';
import {generatedDirectory} from './prepare.mjs';

export const palettePath = 'docs/assets/lsf-palette.json';
const schema = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/palette.schema.json'), 'utf8'));
const validateSchema = new Ajv({allErrors: true, strict: true}).compile(schema);
export const syntaxTokens = ['Text', 'Comment', 'Keyword', 'String', 'Number', 'Function', 'Variable'];
export const statuses = ['success', 'warning', 'danger', 'info'];

export function contrast(foreground, background) {
  function luminance(color) {
    const channels = color.slice(1).match(/../g).map(value => Number.parseInt(value, 16) / 255)
      .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  }
  const values = [luminance(foreground), luminance(background)].sort((left, right) => right - left);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

export function approvedPairs() {
  const pairs = [];
  function add(foreground, backgrounds, minimum = 4.5) {
    for (const background of backgrounds) pairs.push({foreground, background, minimum});
  }
  for (const foreground of ['text', 'muted', 'link', 'linkHover']) add(foreground, ['canvas', 'surface', 'raised']);
  for (const foreground of ['focus', 'border']) add(foreground, ['canvas', 'surface', 'raised'], 3);
  for (const foreground of syntaxTokens) add(`code${foreground}`, ['codeSurface', 'raised']);
  add('controlText', ['controlSurface', 'controlHover']);
  add('controlSurface', ['canvas', 'surface', 'raised'], 3);
  add('disabledText', ['disabledSurface']);
  add('tabText', ['tabSurface']);
  add('selectionInk', ['selection']);
  add('accentInk', ['accent']);
  for (const status of statuses) {
    add(`${status}Text`, [`${status}Surface`]);
    add(`${status}Border`, [`${status}Surface`, 'canvas'], 3);
  }
  return pairs;
}

export function validatePalette(palette) {
  requireValue(validateSchema(palette), `Invalid semantic palette: ${JSON.stringify(validateSchema.errors)}`);
  const results = [];
  for (const [mode, tokens] of Object.entries(palette.modes)) {
    for (const pair of approvedPairs()) {
      const ratio = contrast(tokens[pair.foreground], tokens[pair.background]);
      requireValue(ratio >= pair.minimum, `${mode} ${pair.foreground}/${pair.background}: ${ratio.toFixed(3)} < ${pair.minimum}`);
      results.push({mode, ...pair, ratio: Number(ratio.toFixed(3))});
    }
  }
  return results;
}

export function loadPalette() {
  const palette = JSON.parse(readSource(repositoryRoot, palettePath, 16384));
  validatePalette(palette);
  return palette;
}

export function paletteCss(palette) {
  validatePalette(palette);
  return Object.entries(palette.modes).map(([mode, tokens]) => {
    const selector = mode === 'light' ? ':root, [data-theme="light"]' : '[data-theme="dark"]';
    const declarations = Object.entries(tokens).map(([name, value]) => `  --lsf-${name.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}: ${value};`);
    return `${selector} {\n  color-scheme: ${mode};\n${declarations.join('\n')}\n}`;
  }).join('\n\n') + `\n\n:root {\n  --lsf-diagram-canvas: ${palette.modes.dark.canvas};\n  --lsf-diagram-text: ${palette.modes.dark.text};\n}\n`;
}

export function prismTheme(tokens) {
  const groups = {
    codeComment: ['comment', 'prolog', 'doctype', 'cdata'],
    codeKeyword: ['keyword', 'tag', 'selector', 'atrule'],
    codeString: ['string', 'char', 'attr-value', 'regex'],
    codeNumber: ['boolean', 'number', 'constant'],
    codeFunction: ['function', 'class-name', 'builtin'],
    codeVariable: ['variable', 'property', 'symbol', 'attr-name', 'operator', 'punctuation'],
  };
  return {plain: {color: tokens.codeText, backgroundColor: tokens.codeSurface}, styles: Object.entries(groups).map(([token, types]) => ({types, style: {color: tokens[token]}}))};
}

export function mermaidOptions(tokens) {
  return {
    securityLevel: 'strict',
    fontFamily: 'system-ui, sans-serif',
    htmlLabels: false,
    themeVariables: {
      darkMode: true, background: tokens.canvas,
      primaryColor: tokens.surface, primaryTextColor: tokens.text, primaryBorderColor: tokens.border,
      secondaryColor: tokens.raised, secondaryTextColor: tokens.text, secondaryBorderColor: tokens.border,
      tertiaryColor: tokens.surface, tertiaryTextColor: tokens.text, tertiaryBorderColor: tokens.border,
      lineColor: tokens.link, textColor: tokens.text, nodeTextColor: tokens.text,
      edgeLabelBackground: tokens.surface, clusterBkg: tokens.raised, clusterBorder: tokens.border,
    },
  };
}

export function preparePalette() {
  const palette = loadPalette();
  const css = paletteCss(palette);
  const directory = generatedDirectory('.generated/theme');
  const relative = `.generated/theme/palette-${sha256(css)}.css`;
  const destination = path.join(directory, path.basename(relative));
  if (fs.existsSync(destination)) requireValue(!fs.lstatSync(destination).isSymbolicLink() && fs.readFileSync(destination, 'utf8') === css, 'Palette output collision or linked file');
  else fs.writeFileSync(destination, css, {flag: 'wx'});
  return {palette, css: `./${relative}`};
}
