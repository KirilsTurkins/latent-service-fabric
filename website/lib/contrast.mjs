import assert from 'node:assert/strict';

// Kept independent of the build inventory and schema loader so rendered reviews
// and their negative tests exercise exactly the same contrast calculation.
export function contrast(foreground, background) {
  function luminance(color) {
    assert.match(color, /^#[0-9a-f]{6}$/i, 'Expected an opaque six-digit hex color');
    const channels = color.slice(1).match(/../g).map(value => Number.parseInt(value, 16) / 255)
      .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  }
  const values = [luminance(foreground), luminance(background)].sort((left, right) => right - left);
  return (values[0] + 0.05) / (values[1] + 0.05);
}
