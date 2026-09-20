import path from 'node:path';
import {visit} from 'unist-util-visit';
import {parseFragment} from 'parse5';
import {assetRoute, canonicalPath, htmlElements, requireValue, resolveLink, safeFile} from '../lib/repository.mjs';
import {fileSource} from '../lib/versions/model.mjs';

function isApprovedAssetUrl(url, options) {
  const baseUrl = options.baseUrl ?? '/latent-service-fabric/';
  return (options.assets ?? []).some(asset => `${baseUrl.slice(0, -1)}${assetRoute(asset)}` === url.split(/[?#]/, 1)[0]);
}

function renderedUrl(index, source, url, options) {
  const resolved = resolveLink(index, source, url, options);
  return !options.image && isApprovedAssetUrl(resolved, options) ? `pathname://${resolved}` : resolved;
}

export function checkHtml(element, index, source, options) {
  requireValue(!['script', 'iframe', 'object', 'embed', 'form', 'base'].includes(element.tagName), `Active HTML is not a prose include: ${source}`);
  for (const attribute of element.attrs ?? []) {
    requireValue(!/^on/i.test(attribute.name), `Executable HTML attribute in prose: ${source}`);
    if (['href', 'src'].includes(attribute.name)) resolveLink(index, source, attribute.value, {...options, image: attribute.name === 'src'});
  }
}

export function transformDocument(tree, index, source, options) {
  const imageDefinitions = new Set();
  const definitions = new Map();
  visit(tree, 'imageReference', node => imageDefinitions.add(node.identifier));
  visit(tree, 'definition', node => definitions.set(node.identifier, {url: node.url, title: node.title}));
  visit(tree, node => {
    if (['imageReference', 'linkReference'].includes(node.type)) {
      const definition = definitions.get(node.identifier);
      requireValue(definition, `Missing link/image definition: ${source}`);
      node.type = node.type === 'imageReference' ? 'image' : 'link';
      node.url = definition.url;
      node.title = definition.title;
    }
    if (['link', 'image', 'definition'].includes(node.type)) {
      node.url = renderedUrl(index, source, node.url, {...options, image: node.type === 'image' || (node.type === 'definition' && imageDefinitions.has(node.identifier))});
    }
    if (node.type === 'image') {
      const attributes = [
        {type: 'mdxJsxAttribute', name: 'src', value: node.url},
        {type: 'mdxJsxAttribute', name: 'alt', value: node.alt ?? ''},
        {type: 'mdxJsxAttribute', name: 'loading', value: 'lazy'},
      ];
      if (node.title) attributes.push({type: 'mdxJsxAttribute', name: 'title', value: node.title});
      node.type = 'mdxJsxTextElement';
      node.name = 'img';
      node.attributes = attributes;
      node.children = [];
      delete node.url;
    }
    if (node.type === 'html') htmlElements(parseFragment(node.value), element => checkHtml(element, index, source, options));
    if (node.type === 'mdxjsEsm') {
      for (const statement of node.data?.estree?.body ?? []) {
        if (statement.source) {
          requireValue(/^@(?:site\/src\/components\/|theme\/)/.test(statement.source.value), `MDX imports must use reviewed site components: ${source}`);
          canonicalPath(statement.source.value);
          if (statement.source.value.startsWith('@site/')) {
            const imported = statement.source.value.replace('@site/', 'website/');
            const candidates = [imported, ...['.tsx', '.jsx', '.ts', '.js', '.mjs', '/index.tsx'].map(suffix => imported + suffix)].filter(candidate => (index.componentPaths ?? index.paths).includes(candidate));
            requireValue(candidates.length === 1, `Missing or ambiguous reviewed MDX component: ${source}`);
            safeFile(index.root, candidates[0]);
          }
        }
      }
    }
    if (['mdxJsxFlowElement', 'mdxJsxTextElement'].includes(node.type)) {
      for (const attribute of node.attributes ?? []) {
        if (['href', 'src'].includes(attribute.name)) {
          requireValue(typeof attribute.value === 'string', `MDX link/asset URLs must be literals: ${source}`);
          attribute.value = renderedUrl(index, source, attribute.value, {...options, image: attribute.name === 'src'});
        }
      }
    }
  });
  return tree;
}

export function remarkRepositoryLinks({index, baseUrl, assets}) {
  return (tree, file) => {
    const source = fileSource(index, file.path);
    transformDocument(tree, index, source, {baseUrl, assets});
  };
}

export function rehypeRepositoryLinks({index, baseUrl, assets}) {
  return (tree, file) => {
    const source = fileSource(index, file.path);
    visit(tree, 'element', node => {
      for (const name of ['href', 'src']) {
        if (typeof node.properties?.[name] === 'string') {
          const original = node.properties[name];
          const url = original.startsWith('pathname://') ? original.slice('pathname://'.length) : original;
          requireValue(original === url || (name === 'href' && isApprovedAssetUrl(url, {baseUrl, assets})), `Only approved static links may bypass document routing: ${source}`);
          node.properties[name] = renderedUrl(index, source, url, {baseUrl, assets, image: name === 'src'});
        }
      }
    });
  };
}
