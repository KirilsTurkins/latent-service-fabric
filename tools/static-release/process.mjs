import {spawn} from 'node:child_process';
import path from 'node:path';
import {requireValue} from './model.mjs';

// Only maintained executables, never shell commands. No caller environment
// tokens, NODE_OPTIONS, Python startup overrides or build flags reach a child.
export async function run(executable, args, directory, seconds = 60) {
  requireValue(path.isAbsolute(executable) && args.every(item => typeof item === 'string')
    && Number.isInteger(seconds) && seconds > 0 && seconds <= 120, 'release-process-input');
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, {cwd: directory, windowsHide: true,
      env: {PATH: '/usr/local/bin:/usr/bin:/bin', HOME: directory, LANG: 'C.UTF-8',
        PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1'}, stdio: ['ignore', 'pipe', 'pipe']});
    let bytes = 0, failure;
    const chunks = [];
    const fail = reason => { failure ??= reason; child.kill('SIGKILL'); };
    const timer = setTimeout(() => fail('release-command-deadline'), seconds * 1000);
    const cancelled = () => fail('release-command-cancelled');
    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, cancelled);
    child.on('error', () => { failure ??= 'release-command-start-failed'; });
    child.stdout.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > 1024 * 1024) fail('release-command-output-bound'); else chunks.push(chunk);
    });
    child.stderr.on('data', chunk => { bytes += chunk.length; if (bytes > 1024 * 1024) fail('release-command-output-bound'); });
    child.on('close', code => {
      clearTimeout(timer);
      for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.off(signal, cancelled);
      if (failure || code !== 0) reject(new Error(failure ?? 'release-command-failed'));
      else resolve(Buffer.concat(chunks));
    });
  });
}
export async function native(cli, args, directory) {
  const result = JSON.parse((await run(cli, ['--output', 'json', ...args], directory)).toString('utf8'));
  requireValue(result.schemaVersion === 'latent.cli.result.v1' && result.category === 'success'
    && result.outcomeKnown === true, 'release-native-command-rejected');
  return result.data;
}
