const {createHash} = require('node:crypto');

// The pinned Docusaurus hook can receive a resize or tab callback after React
// clears its DOM ref but before passive-effect cleanup removes the listener.
// Apply this small fix to the authenticated original, retaining its imports,
// active wrapping behavior and listener cleanup. Review it on a pin refresh.
const originalSha256 = '3483ac26c8c5cb90064902fb63a5256576092207a86b572480a04a8fb103b012';
const replacements = [
  ["const codeElement = codeBlockRef.current.querySelector('code');",
    "const codeElement = codeBlockRef.current?.querySelector('code');\n        if (!codeElement) return;"],
  ['const { scrollWidth, clientWidth } = codeBlockRef.current;',
    'const block = codeBlockRef.current;\n        if (!block) return;\n        const { scrollWidth, clientWidth } = block;'],
  ["codeBlockRef.current.querySelector('code').hasAttribute('style');",
    "block.querySelector('code')?.hasAttribute('style') === true;"],
];

module.exports = function codeWordWrapLoader(source) {
  this.cacheable?.();
  if (createHash('sha256').update(source).digest('hex') !== originalSha256) {
    throw new Error('Review the code-word-wrap lifecycle fix for the changed Docusaurus hook');
  }
  let result = source;
  for (const [original, replacement] of replacements) {
    if (result.split(original).length !== 2) throw new Error('Unexpected code-word-wrap hook shape');
    result = result.replace(original, replacement);
  }
  return result;
};
