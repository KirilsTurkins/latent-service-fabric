import {resolveExample} from './resolve.mjs';

const labels = {rust: 'Rust', typescript: 'TypeScript', go: 'Go', c: 'C', java: 'Java', csharp: 'C#/.NET'};
function reference(node) {
  if (node.type !== 'html') return null;
  const match = /^<!-- lsf-example: ((?:client|browser|guest)\/[a-z][a-z0-9-]{0,119}) ([a-z][a-z0-9-]{0,63}) -->$/.exec(node.value.trim());
  if (!match && /^<!--\s*lsf-example\b/.test(node.value.trim())) throw new Error('Malformed public example reference');
  return match ? {example: match[1], region: match[2]} : null;
}
function componentRequest(node) {
  if (node.type !== 'mdxJsxFlowElement' || node.name !== 'CodeExample') return null;
  const attributes = node.attributes ?? [];
  if (attributes.length !== 2 || new Set(attributes.map(attribute => attribute.name)).size !== 2
    || attributes.some(attribute => attribute.type !== 'mdxJsxAttribute'
      || !['example', 'region'].includes(attribute.name) || typeof attribute.value !== 'string')) {
    throw new Error('CodeExample requires literal example and region attributes only');
  }
  return Object.fromEntries(attributes.map(attribute => [attribute.name, attribute.value]));
}
export function requestsFromTree(tree) {
  const requests = [];
  function walk(node) {
    const request = reference(node) ?? componentRequest(node);
    if (request) requests.push(request);
    if (requests.length > 256) throw new Error('Example document request limit');
    for (const child of node.children ?? []) walk(child);
  }
  walk(tree);
  return requests;
}
const text = value => ({type: 'text', value});
const paragraph = value => ({type: 'paragraph', children: [text(value)]});
const link = (label, url) => ({type: 'link', url, children: [text(label)]});

export function exampleNodes(bundle, request, {includeVerification = true} = {}) {
  const selected = resolveExample(bundle, request);
  const nodes = [paragraph(selected.title)];
  for (const variant of selected.variants) {
    const {source, snippet, verification} = variant;
    nodes.push(paragraph(labels[variant.language]));
    // Code is a value in an mdast code node, never an HTML node, MDX expression,
    // evaluated import or interpolated Markdown fence. Preserve the exact bytes.
    nodes.push({type: 'code', lang: variant.language, meta: null, value: snippet.code});
    if (!includeVerification) {
      if (source.url) nodes.push({type: 'paragraph', children: [link('View complete source', source.url)]});
      continue;
    }
    nodes.push(paragraph(`Source SHA-256: ${source.sha256}. Snippet SHA-256: ${snippet.sha256}.`));
    nodes.push({type: 'paragraph', children: [
      ...(source.url ? [link(`Complete source at ${source.revision.slice(0, 12)}`, source.url), text(' · ')] : [text('Uncommitted working copy; no commit-bound source link. ')]),
      ...(variant.validation.target ? [link('Validation target (not executed by this site)', variant.validation.target), text(' · ')] : [text('Validation target is an uncommitted working copy. ')]),
      ...(variant.validation.instructions ? [link('Owner instructions', variant.validation.instructions)] : [text('Owner instructions are an uncommitted working copy.')]),
    ]});
    nodes.push(paragraph(verification.level === 'source-extracted'
      ? `Verification: source extraction only (${verification.reason}); not compilation or real-node proof.`
      : `Verification: ${verification.level}, ${verification.execution}, from a reviewed record; source ${verification.sourceRevision}, toolchain ${verification.toolchain}, run ${verification.run}. Scope: ${verification.scope}. The website did not run this validation.`));
  }
  return nodes;
}
export function remarkExamples({bundle, documentVersion, includeVerification = true}) {
  return tree => {
    function transform(parent) {
      if (!parent.children) return;
      parent.children = parent.children.flatMap(node => {
        const request = reference(node);
        if (request) return exampleNodes(bundle, {...request, documentVersion}, {includeVerification});
        const component = componentRequest(node);
        if (component) {
          resolveExample(bundle, {...component, documentVersion});
          node.attributes.push({type: 'mdxJsxAttribute', name: 'documentVersion', value: documentVersion});
        }
        transform(node);
        return [node];
      });
    }
    transform(tree);
    return tree;
  };
}
