#!/usr/bin/env node
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseArgs} from 'node:util';
import {prepare} from './prepare.mjs';
import {requestApproval, signEvidence} from './evidence.mjs';
import {requireValue} from './model.mjs';

export async function main(args) {
  const names = ['cli', 'python', 'build-output', 'inventory', 'repository', 'output', 'prepared', 'approval',
    'publisher-key', 'builder-key', 'policy', 'tenant', 'identities', 'lifetime-seconds'];
  const {values, positionals} = parseArgs({args, allowPositionals: true, strict: true,
    options: Object.fromEntries(names.map(name => [name, {type: 'string'}]))});
  const command = positionals[0];
  const selected = command === 'prepare' ? ['cli', 'python', 'build-output', 'inventory', 'repository', 'output']
    : command === 'sign' ? ['cli', 'prepared', 'approval', 'publisher-key', 'builder-key', 'output', 'policy', 'tenant']
      : command === 'request-signing' ? ['prepared', 'identities', 'lifetime-seconds', 'output'] : [];
  requireValue(positionals.length === 1 && selected.length > 0 && Object.keys(values).length === selected.length
    && selected.every(name => typeof values[name] === 'string' && values[name].length > 0 && values[name].length <= 4096),
    'explicit-release-arguments-required');
  const resolve = name => path.resolve(values[name]);
  if (command === 'prepare') return prepare({cli: resolve('cli'), python: resolve('python'), buildOutput: resolve('build-output'),
    inventory: resolve('inventory'), repository: values.repository, output: resolve('output')});
  if (command === 'request-signing') return requestApproval({directory: resolve('prepared'), identitiesFile: resolve('identities'),
    lifetimeSeconds: Number(values['lifetime-seconds']), output: resolve('output')});
  return signEvidence({cli: resolve('cli'), directory: resolve('prepared'), approvalFile: resolve('approval'),
    publisherKey: resolve('publisher-key'), builderKey: resolve('builder-key'), output: resolve('output'),
    policy: resolve('policy'), tenant: values.tenant});
}
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try { console.log(JSON.stringify(await main(process.argv.slice(2)))); }
  catch (error) {
    const reason = /^[a-z][a-z-]{0,95}$/.test(error.message) ? error.message : 'static-release-input-or-command-failed';
    console.log(JSON.stringify({schemaVersion: 'latent.static.release-result.v1', status: 'failed', reason}));
    process.exitCode = 2;
  }
}
