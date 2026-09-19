import path from 'node:path';
import {spawn, spawnSync} from 'node:child_process';
import {basePath, requireValue, websiteRoot} from '../lib/repository.mjs';

requireValue(process.versions.node === '24.19.0', 'Use the reviewed website Node 24.19.0 toolchain');
const command = process.argv[2];
requireValue(['start', 'build', 'build-root', 'test-build', 'test-theme', 'browser-install'].includes(command) && process.argv.length === 3, 'Use a documented website command without arbitrary output paths');
const rootBuild = command === 'build-root';
const baseUrl = basePath(rootBuild ? '/' : '/latent-service-fabric/');
let args = command === 'start'
  ? ['start', '--host', '127.0.0.1', '--port', '3000', '--no-open']
  : ['build', '--out-dir', rootBuild ? 'build/root' : 'build/project'];
let program = path.join(websiteRoot, 'node_modules/@docusaurus/core/bin/docusaurus.mjs');
if (command === 'test-build') { program = path.join(websiteRoot, 'scripts/test-build.mjs'); args = []; }
if (command === 'test-theme') { program = path.join(websiteRoot, 'scripts/test-theme.mjs'); args = []; }
if (command === 'browser-install') { program = path.join(websiteRoot, 'node_modules/playwright/cli.js'); args = ['install', 'chromium', '--only-shell']; }
const child = spawn(process.execPath, [program, ...args], {
  cwd: websiteRoot,
  stdio: 'inherit',
  detached: process.platform !== 'win32',
  env: {...process.env, LSF_SITE_BASE_URL: baseUrl, LSF_SITE_URL: rootBuild ? 'https://docs.example.invalid' : 'https://kirilsturkins.github.io', PLAYWRIGHT_BROWSERS_PATH: path.join(websiteRoot, '.generated/browsers'), DOCUSAURUS_SSR_CONCURRENCY: '2', DOCUSAURUS_SSG_WORKER_THREAD_COUNT: '2', NODE_OPTIONS: '--max-old-space-size=4096'},
});
let expired = false;
function stop() {
  if (!child.pid || child.exitCode !== null) return;
  if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], {timeout: 15000, stdio: 'ignore'});
  else process.kill(-child.pid, 'SIGKILL');
}
const timer = command === 'start' ? undefined : setTimeout(() => { expired = true; stop(); }, command === 'test-theme' ? 300000 : ['test-build', 'browser-install'].includes(command) ? 180000 : 600000);
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
child.on('error', error => { clearTimeout(timer); console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { clearTimeout(timer); process.exitCode = expired ? 1 : (code ?? 1); });
