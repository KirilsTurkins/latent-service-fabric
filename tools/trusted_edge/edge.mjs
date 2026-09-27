// One bounded, trusted TLS edge. No DNS, credentials, route rules or public management.
import https from 'node:https';
import {configuration, LIMITS, requireEdge} from './config.mjs';
import {admitted, reject} from './request.mjs';
import {upstream} from './upstream.mjs';
import {compressed} from './compressed.mjs';
import {encoding, conditions} from './representation.mjs';

export async function start(file) {
  const {value: config, cert, key} = await configuration(file);
  const compress = config.compression === 'gzip', maximumExchanges = compress ? 4 : LIMITS.exchanges;
  let active = 0, accepting = true, completed = 0, cancelled = 0, denied = 0;
  let listenerClosed = false, reported = false;
  const sockets = new Set(), owners = new Set();
  const reportStopped = () => {
    if (reported || !listenerClosed || active !== 0) return;
    reported = true;
    console.log(JSON.stringify({event: 'stopped', active, sockets: sockets.size, completed, cancelled, denied,
      residentBytes: process.memoryUsage().rss, cloudQualified: false}));
  };
  const server = https.createServer({cert, key, minVersion: 'TLSv1.2', ALPNProtocols: ['http/1.1'],
    handshakeTimeout: 2000, headersTimeout: 2000, requestTimeout: 2000, connectionsCheckingInterval: 250,
    maxHeaderSize: LIMITS.headerBytes, highWaterMark: 16384}, async (request, response) => {
    let headers, selected, condition;
    try {
      headers = admitted(request, config.authority);
      if (compress) { selected = encoding(headers['accept-encoding']); condition = conditions(headers); }
    }
    catch { denied++; reject(response); return; }
    if (!accepting || active >= maximumExchanges) { denied++; reject(response, 503); return; }
    active++;
    const owner = {upstreams: new Set(), abort: null, aborted: false, done: false}; owners.add(owner);
    let settled = false, downstreamClosed = false;
    const release = () => {
      if (settled || !downstreamClosed || !owner.done || owner.upstreams.size) return;
      settled = true; clearTimeout(timer); owners.delete(owner); active--; reportStopped();
    };
    owner.abort = () => {
      if (settled || owner.aborted) return;
      owner.aborted = true; cancelled++;
      for (const call of owner.upstreams) call.destroy(new Error('edge-cancelled'));
      response.destroy();
    };
    const timer = setTimeout(owner.abort, LIMITS.seconds * 1000);
    response.once('close', () => {
      downstreamClosed = true;
      if (!response.writableFinished) owner.abort();
      release();
    });
    request.once('aborted', owner.abort);
    try {
      if (compress) await compressed(request, response, headers, config, owner, release, selected, condition);
      else await upstream(request, headers, config, owner, release, response, false);
      if (!owner.aborted) completed++;
    } catch { denied++; reject(response, 502); }
    finally { owner.done = true; release(); }
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
    server.close(() => { listenerClosed = true; reportStopped(); });
    for (const owner of owners) owner.abort();
    for (const socket of sockets) socket.destroy();
    server.closeAllConnections();
  };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  console.log(JSON.stringify({event: 'listening', profile: 'latent.local-tls-edge.v1', fixedPeer: '127.0.0.2',
    limits: {...LIMITS, exchanges: maximumExchanges}, compression: config.compression ?? 'none', cloudQualified: false}));
  return {server, stop};
}

if (process.argv[1]?.endsWith('/edge.mjs')) {
  try { requireEdge(process.argv.length === 3, 'edge-one-config-file-required'); await start(process.argv[2]); }
  catch { console.error('{"event":"failed","reason":"edge-protected-configuration-or-listener-failed"}'); process.exitCode = 1; }
}
