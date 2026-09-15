// This wrapper is compiled into the application artifact and observed as a
// build material. The node's fixed adapter independently caps total output.
import {render as applicationRender} from './server.js';
import {clientAsset} from './assets.js';
function bytes(text) {
  let count = 0;
  for (const point of text) count += point.codePointAt(0) < 128 ? 1 : point.codePointAt(0) < 2048 ? 2 : point.length === 2 ? 4 : 3;
  return count;
}
export async function render(request, context) {
  const result = await applicationRender(request, context);
  if (!result || typeof result.html !== 'string' || result.html.length > 131072) throw new Error('angular-render-result');
  const html = result.html.replaceAll('__LSF_CLIENT_ASSET__', clientAsset);
  if (bytes(html) > 131072) throw new Error('angular-html-limit');
  let transferred = 0, scripts = 0;
  const tags = /<script\b([^>]*)>/gi;
  let match;
  while ((match = tags.exec(html))) {
    if (++scripts > 64) throw new Error('angular-script-count');
    // Closed generated-script syntax avoids an HTML character-reference or
    // malformed-attribute spelling evading the transfer-data ceiling.
    if (match[1].includes('&') || !/^(?:\s+[a-zA-Z0-9_-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'`=<>]+))?)*\s*$/.test(match[1])) {
      throw new Error('angular-script-attributes');
    }
    const closing = /<\/script\s*>/gi;
    closing.lastIndex = tags.lastIndex;
    const end = closing.exec(html);
    if (!end) throw new Error('angular-script-incomplete');
    if (/\btype\s*=\s*(?:"application\/json"|'application\/json'|application\/json(?=\s|$))/i.test(match[1])) {
      const data = html.slice(tags.lastIndex, end.index);
      transferred += bytes(data);
      if (transferred > 32768) throw new Error('angular-hydration-limit');
      JSON.parse(data);
    }
    tags.lastIndex = closing.lastIndex;
  }
  return {...result, html};
}
