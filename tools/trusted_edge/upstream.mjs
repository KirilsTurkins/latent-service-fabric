import http from 'node:http';
import {LIMITS, requireEdge} from './config.mjs';
import {responseHeaders} from './request.mjs';

// Each socket belongs to the existing exchange, including a second GET used to
// determine a gzip HEAD representation. No retry, DNS, pool, cache or queue.
export function upstream(request, headers, config, owner, release, response, buffered, method = request.method) {
  return new Promise((resolve, reject) => {
    if (owner.aborted) { reject(new Error('edge-cancelled')); return; }
    const call = http.request({host: '127.0.0.1', port: config.upstreamPort, localAddress: '127.0.0.2',
      agent: false, method, path: request.url, headers, maxHeaderSize: LIMITS.headerBytes}, incoming => {
      try {
        const outgoing = responseHeaders(incoming);
        const value = incoming.headers['content-length'] ?? ([204, 304].includes(incoming.statusCode) ? '0' : undefined);
        requireEdge(typeof value === 'string' && /^(0|[1-9][0-9]{0,7})$/.test(value)
          && Number(value) <= LIMITS.responseBytes, 'edge-upstream-body-bound');
        const length = Number(value), bodyless = method === 'HEAD' || [204, 304].includes(incoming.statusCode);
        const body = buffered ? Buffer.alloc(bodyless ? 0 : length) : null;
        let received = 0;
        if (!buffered) response.writeHead(incoming.statusCode, outgoing);
        incoming.on('data', block => {
          received += block.length;
          if (bodyless || received > length) { call.destroy(new Error('edge-upstream-body-mismatch')); return; }
          if (buffered) block.copy(body, received - block.length);
          else if (!response.write(block)) incoming.pause();
        });
        if (!buffered) response.on('drain', () => incoming.resume());
        incoming.on('end', () => {
          if (!bodyless && received !== length) { reject(new Error('edge-truncated-upstream')); return; }
          if (!buffered) response.end();
          resolve({code: incoming.statusCode, headers: outgoing, body, length});
        });
        incoming.on('error', reject);
      } catch (error) { incoming.destroy(); reject(error); }
    });
    owner.upstreams.add(call);
    call.once('close', () => { owner.upstreams.delete(call); release(); });
    call.once('error', reject); call.end();
  });
}
