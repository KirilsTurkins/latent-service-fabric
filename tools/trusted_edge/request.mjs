import {LIMITS, requireEdge} from './config.mjs';

export function admitted(request, authority) {
  requireEdge(request.httpVersion === '1.1' && ['GET', 'HEAD'].includes(request.method), 'edge-read-method');
  requireEdge(typeof request.url === 'string' && request.url.startsWith('/') && !request.url.startsWith('//')
    && !request.url.startsWith('/__lsf/') && request.url.length <= 4096, 'edge-origin-form-target');
  requireEdge(request.rawHeaders.length <= 2 * LIMITS.headers && request.headers.host === authority, 'edge-authority-or-headers');
  const names = new Set();
  for (let index = 0; index < request.rawHeaders.length; index += 2) {
    const name = request.rawHeaders[index].toLowerCase();
    requireEdge(!names.has(name), 'edge-duplicate-header'); names.add(name);
    requireEdge(!/^(forwarded|x-forwarded-.+|x-lsf-.+|x-latent-.+|x-tenant(?:-id)?|x-principal(?:-id)?|traceparent|tracestate|baggage|grpc-timeout)$/i.test(name),
      'edge-untrusted-authority-header');
  }
  requireEdge(!names.has('transfer-encoding') && !names.has('expect') && !names.has('upgrade')
    && !names.has('proxy-authorization') && !names.has('proxy-connection')
    && (!names.has('content-length') || request.headers['content-length'] === '0'), 'edge-body-or-hop-header');
  requireEdge(!names.has('connection') || ['close', 'keep-alive'].includes(request.headers.connection.toLowerCase()),
    'edge-connection-token');
  // Origin and every Sec-Fetch-* field retain their original meaning. No edge
  // header can authorize a tenant, browser exception, trace or deadline.
  return {...request.headers, connection: 'close'};
}

export function responseHeaders(response) {
  requireEdge(response.rawHeaders.length <= 2 * LIMITS.headers, 'edge-upstream-header-bound');
  requireEdge(!response.headers['transfer-encoding'] && !response.headers['content-encoding'], 'edge-identity-upstream-required');
  const headers = {...response.headers};
  delete headers.connection; delete headers['keep-alive'];
  requireEdge(typeof headers['content-security-policy'] === 'string'
    && headers['x-content-type-options'] === 'nosniff'
    && headers['strict-transport-security'] === 'max-age=31536000', 'edge-native-browser-policy-required');
  return {...headers, connection: 'close'};
}

export function reject(response, code = 400) {
  if (response.destroyed) return;
  if (response.headersSent) { response.destroy(); return; }
  response.writeHead(code, {'content-length': '0', 'cache-control': 'no-store', connection: 'close',
    'content-security-policy': "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'",
    'x-content-type-options': 'nosniff', 'x-frame-options': 'DENY', 'referrer-policy': 'same-origin',
    'cross-origin-opener-policy': 'same-origin', 'cross-origin-resource-policy': 'same-origin',
    'permissions-policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
    'strict-transport-security': 'max-age=31536000'});
  response.end();
}
