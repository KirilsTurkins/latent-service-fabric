// One bounded, trusted TLS edge. No DNS, credentials, route rules or public management.
import https from 'node:https';
import http from 'node:http';
import {configuration, LIMITS, requireEdge} from './config.mjs';
import {admitted, responseHeaders, reject} from './request.mjs';

export async function start(file) {
  const {value: config, cert, key} = await configuration(file);
  let active = 0, accepting = true, completed = 0, cancelled = 0, denied = 0;
  const sockets = new Set(), owners = new Set();
  const server = https.createServer({cert, key, minVersion: 'TLSv1.2', ALPNProtocols: ['http/1.1'],
    handshakeTimeout: 2000, headersTimeout: 2000, requestTimeout: 2000, connectionsCheckingInterval: 250,
    maxHeaderSize: LIMITS.headerBytes, highWaterMark: 16384}, async (request, response) => {
    let headers;
    try { headers = admitted(request, config.authority); }
    catch { denied++; reject(response); return; }
    if (!accepting || active >= LIMITS.exchanges) { denied++; reject(response, 503); return; }
    active++;
    const owner = {upstream: null, abort: null}; owners.add(owner);
    let settled = false, downstreamClosed = false, upstreamClosed = false;
    const release = () => {
      if (settled || !downstreamClosed || !upstreamClosed) return;
      settled = true; clearTimeout(timer); owners.delete(owner); active--;
    };
    owner.abort = () => { if (!settled) { cancelled++; owner.upstream?.destroy(); response.destroy(); } };
    const timer = setTimeout(owner.abort, LIMITS.seconds * 1000);
    response.once('close', () => {
      downstreamClosed = true;
      if (!response.writableFinished) cancelled++;
      owner.upstream?.destroy(); release();
    });
    request.once('aborted', owner.abort);
    try {
      const upstream = http.request({host: '127.0.0.1', port: config.upstreamPort, localAddress: '127.0.0.2',
        agent: false, method: request.method, path: request.url, headers, maxHeaderSize: LIMITS.headerBytes}, incoming => {
        try {
          const outgoing = responseHeaders(incoming);
          const length = incoming.headers['content-length'] ?? ([204, 304].includes(incoming.statusCode) ? '0' : undefined);
          requireEdge(typeof length === 'string' && /^(0|[1-9][0-9]{0,7})$/.test(length)
            && Number(length) <= LIMITS.responseBytes, 'edge-upstream-body-bound');
          response.writeHead(incoming.statusCode, outgoing);
          let bytes = 0;
          incoming.on('data', block => {
            bytes += block.length;
            if (bytes > LIMITS.responseBytes || bytes > Number(length)) { owner.abort(); return; }
            if (!response.write(block)) incoming.pause();
          });
          response.on('drain', () => incoming.resume());
          incoming.on('end', () => {
            if (request.method !== 'HEAD' && ![204, 304].includes(incoming.statusCode) && bytes !== Number(length)) {
              owner.abort(); return;
            }
            completed++; response.end();
          });
          incoming.on('error', owner.abort);
        } catch { denied++; incoming.destroy(); reject(response, 502); }
      });
      owner.upstream = upstream;
      upstream.once('close', () => { upstreamClosed = true; release(); });
      upstream.on('error', () => { reject(response, 502); });
      upstream.end();
    } catch { upstreamClosed = true; reject(response, 502); }
  });
  key.fill(0);
  server.maxHeadersCount = LIMITS.headers;
  server.maxRequestsPerSocket = 1;
  server.maxConnections = LIMITS.connections;
  server.setTimeout(2000, socket => socket.destroy());
  server.on('connection', socket => {
    sockets.add(socket); socket.once('close', () => sockets.delete(socket));
    const lifetime = setTimeout(() => socket.destroy(), LIMITS.seconds * 1000);
    socket.once('close', () => clearTimeout(lifetime));
    socket.on('error', () => {});
  });
  server.on('tlsClientError', () => {});
  server.on('clientError', (_error, socket) => socket.destroy());
  server.on('upgrade', (_request, socket) => socket.destroy());
  server.on('connect', (_request, socket) => socket.destroy());
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen({host: config.bind, port: config.port, backlog: 16}, resolve);
  });
  let stopped = false;
  const stop = () => {
    if (stopped) return; stopped = true; accepting = false;
    server.close(() => {
      console.log(JSON.stringify({event: 'stopped', active, sockets: sockets.size, completed, cancelled, denied,
        residentBytes: process.memoryUsage().rss, cloudQualified: false}));
    });
    for (const owner of owners) owner.abort();
    for (const socket of sockets) socket.destroy();
    server.closeAllConnections();
  };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  console.log(JSON.stringify({event: 'listening', profile: 'latent.local-tls-edge.v1', fixedPeer: '127.0.0.2',
    limits: LIMITS, cloudQualified: false}));
  return {server, stop};
}

if (process.argv[1]?.endsWith('/edge.mjs')) {
  try { requireEdge(process.argv.length === 3, 'edge-one-config-file-required'); await start(process.argv[2]); }
  catch { console.error('{"event":"failed","reason":"edge-protected-configuration-or-listener-failed"}'); process.exitCode = 1; }
}
