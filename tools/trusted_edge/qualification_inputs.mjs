// Fresh qualification identities only. Production never calls this generator.
import '../container_runtime/qualification_inputs.mjs';
import {mkdir, readFile, writeFile, chmod} from 'node:fs/promises';
import {run} from '../static-release/process.mjs';
import {jsonBytes} from '../static-release/files.mjs';

await mkdir('/edge/tls', {mode: 0o700});
await run('/usr/bin/openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
  '-subj', '/CN=frontend.example.test', '-addext', 'subjectAltName=DNS:frontend.example.test',
  '-keyout', '/edge/tls/server-key.pem', '-out', '/edge/tls/server.pem'], '/edge');
for (const file of ['server.pem', 'server-key.pem']) await chmod('/edge/tls/' + file, 0o600);
await writeFile('/edge/edge.json', jsonBytes({formatVersion: 1, authority: 'frontend.example.test:18443',
  bind: '127.0.0.1', port: 18443, upstreamPort: 18080,
  certificate: '/etc/lsf/tls/server.pem', privateKey: '/etc/lsf/tls/server-key.pem'}), {mode: 0o600, flag: 'wx'});
const config = JSON.parse(await readFile('/config/node.json', 'utf8'));
config.httpIngress.transport = {mode: 'trusted-proxy', peers: ['127.0.0.2']};
config.httpIngress.authentication.origins[0].authority = 'frontend.example.test:18443';
config.httpIngress.limits.maximumConnections = 16;
config.httpIngress.limits.maximumExchanges = 8;
config.httpIngress.limits.maximumBufferBytes = 48 * 1024 * 1024;
await writeFile('/config/node.json', jsonBytes(config), {mode: 0o600});
console.log(JSON.stringify({edgeInputs: true, exactPeer: '127.0.0.2', disposableTlsIdentity: true}));
