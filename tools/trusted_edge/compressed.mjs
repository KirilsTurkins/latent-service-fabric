import {requireEdge} from './config.mjs';
import {upstream} from './upstream.mjs';
import {conditionalCode, transform, vary} from './representation.mjs';

export async function compressed(request, response, headers, config, owner, release, selected, condition) {
  const nativeHeaders = {...headers};
  for (const name of ['accept-encoding', 'if-match', 'if-none-match']) delete nativeHeaders[name];
  // First authorize the actual method and its route. HEAD and GET are separate
  // declarations in LSF; never substitute GET for HEAD authorization.
  let original = await upstream(request, nativeHeaders, config, owner, release, response, true);
  if (owner.aborted) return;
  let outgoing = vary(original.headers), body = original.body;
  if (original.code !== 200) {
    response.writeHead(original.code, outgoing); response.end(body); return;
  }
  if (selected === null) {
    delete outgoing.etag; outgoing['content-length'] = '0'; outgoing['cache-control'] = 'no-store';
    response.writeHead(406, outgoing); response.end(); return;
  }
  requireEdge(typeof outgoing.etag === 'string' && /^"identity-sha256-[0-9a-f]{64}"$/.test(outgoing.etag),
    'edge-immutable-native-validator-required');
  if (selected === 'gzip') {
    if (request.method === 'HEAD') {
      const head = original;
      original = await upstream(request, nativeHeaders, config, owner, release, response, true, 'GET');
      requireEdge(original.code === 200 && original.length === head.length
        && ['etag', 'content-type', 'content-security-policy', 'cache-control', 'vary'].every(name =>
          original.headers[name] === head.headers[name]), 'edge-head-get-representation-mismatch');
      body = original.body;
    }
    if (owner.aborted) return;
    const result = await transform(body, outgoing['content-type']);
    if (owner.aborted) return;
    body = result.bytes; outgoing.etag = result.etag; outgoing['content-encoding'] = 'gzip';
    outgoing['content-length'] = String(body.length);
  }
  const code = conditionalCode(outgoing.etag, condition);
  if (code === 304) delete outgoing['content-length'];
  if (code === 412) {
    delete outgoing['content-encoding']; outgoing['content-length'] = '0'; outgoing['cache-control'] = 'no-store';
  }
  response.writeHead(code, outgoing);
  response.end(code === 200 && request.method !== 'HEAD' ? body : undefined);
}
