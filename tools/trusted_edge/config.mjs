import {isIP} from 'node:net';
import {boundedJson, closed, readBytes} from '../static-release/files.mjs';
import {requireValue} from '../static-release/model.mjs';

export const requireEdge = requireValue;
export const LIMITS = Object.freeze({connections: 16, exchanges: 8, headers: 32,
  headerBytes: 8192, responseBytes: 8 * 1024 * 1024, seconds: 5});

export async function configuration(file) {
  requireEdge(process.platform === 'linux' && process.getuid() === 10001 && process.getgid() === 10001,
    'edge-linux-uid-gid-10001-required');
  const value = boundedJson(await readBytes(file, 8192, true), 8192);
  closed(value, ['formatVersion', 'authority', 'bind', 'port', 'upstreamPort', 'certificate', 'privateKey']);
  requireEdge(value.formatVersion === 1 && isIP(value.bind) === 4, 'edge-profile-or-bind');
  requireEdge(typeof value.authority === 'string' && value.authority.length <= 253
    && /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*(?::[1-9][0-9]{0,4})?$/.test(value.authority), 'edge-exact-authority');
  for (const key of ['port', 'upstreamPort']) requireEdge(Number.isInteger(value[key]) && value[key] >= 1024
    && value[key] <= 65535, 'edge-port');
  requireEdge(value.port !== value.upstreamPort, 'edge-cannot-forward-to-itself');
  requireEdge(value.certificate === '/etc/lsf/tls/server.pem' && value.privateKey === '/etc/lsf/tls/server-key.pem',
    'edge-fixed-protected-tls-inputs');
  return {value, cert: await readBytes(value.certificate, 65536, true), key: await readBytes(value.privateKey, 16384, true)};
}
