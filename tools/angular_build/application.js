// This wrapper is compiled into the application artifact and observed as a
// build material. The node's fixed adapter independently caps total output.
import * as application from './server.js';
import {clientAsset} from './assets.js';
function bytes(text) {
  let count = 0;
  for (const point of text) count += point.codePointAt(0) < 128 ? 1 : point.codePointAt(0) < 2048 ? 2 : point.length === 2 ? 4 : 3;
  return count;
}
function transfersState(attributes) {
  // Keep this closed attribute grammar and recognition in sync with package.py.
  // Parse real attributes: data-type or a quoted value containing "type=" is not
  // a MIME attribute. Reject duplicates instead of choosing conflicting values.
  if (attributes.includes('&') || !/^(?:[ \t\n\f\r]+[a-zA-Z0-9_-]+(?:[ \t\n\f\r]*=[ \t\n\f\r]*(?:"[^"]*"|'[^']*'|[^ \t\n\f\r"'`=<>]+))?)*[ \t\n\f\r]*$/.test(attributes)) {
    throw new Error('angular-script-attributes');
  }
  const values = new Map();
  const pattern = /[ \t\n\f\r]+([a-zA-Z0-9_-]+)(?:[ \t\n\f\r]*=[ \t\n\f\r]*(?:"([^"]*)"|'([^']*)'|([^ \t\n\f\r"'`=<>]+)))?/g;
  for (const attribute of attributes.matchAll(pattern)) {
    const name = attribute[1].toLowerCase();
    if (values.has(name)) throw new Error('angular-script-attributes');
    values.set(name, attribute[2] ?? attribute[3] ?? attribute[4] ?? '');
  }
  const type = (values.get('type') ?? '').replace(/^[ \t\n\f\r]+|[ \t\n\f\r]+$/g, '').toLowerCase();
  // Angular looks up `${appId}-state` by ID, independently of the MIME type.
  // IDs themselves are case-sensitive and must not be trimmed or lowercased.
  return type === 'application/json' || (values.get('id') ?? '').endsWith('-state');
}
export async function prepare(request, context) {
  if (typeof application.prepare !== 'function') return null;
  return await application.prepare(request, context);
}

export async function render(request, context, backend = null) {
  const result = await application.render(request, context, backend);
  if (!result || typeof result.html !== 'string' || result.html.length > 131072) throw new Error('angular-render-result');
  const html = result.html.replaceAll('__LSF_CLIENT_ASSET__', clientAsset);
  if (bytes(html) > 131072) throw new Error('angular-html-limit');
  let transferred = 0, scripts = 0;
  const tags = /<script\b((?:"[^"]*"|'[^']*'|[^'">])*)>/gi;
  let match;
  while ((match = tags.exec(html))) {
    if (++scripts > 64) throw new Error('angular-script-count');
    const transfer = transfersState(match[1]);
    const closing = /<\/script[ \t\n\f\r]*>/gi;
    closing.lastIndex = tags.lastIndex;
    const end = closing.exec(html);
    if (!end) throw new Error('angular-script-incomplete');
    if (transfer) {
      const data = html.slice(tags.lastIndex, end.index);
      transferred += bytes(data);
      if (transferred > 32768) throw new Error('angular-hydration-limit');
      JSON.parse(data);
    }
    tags.lastIndex = closing.lastIndex;
  }
  return {...result, html};
}
