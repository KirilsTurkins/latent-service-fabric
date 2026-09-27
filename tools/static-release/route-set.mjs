#!/usr/bin/env node
import path from 'node:path';
import {parseArgs} from 'node:util';
import {fileURLToPath} from 'node:url';
import {connection, durableWrite, locked, readJson} from './io.mjs';
import {plan, requireValue, validateJournal} from './model.mjs';
import {reconcile} from './reconcile.mjs';

export async function main(argv) {
  const {values, positionals} = parseArgs({args: argv, allowPositionals: true, strict: true, options: {
    cli: {type: 'string'}, config: {type: 'string'}, profile: {type: 'string'}, node: {type: 'string'},
    intent: {type: 'string'}, journal: {type: 'string'}, 'deadline-seconds': {type: 'string', default: '120'},
    'maximum-writes': {type: 'string', default: '16'},
  }});
  const command = positionals[0];
  requireValue(positionals.length === 1 && ['plan', 'apply', 'status'].includes(command), 'plan-apply-or-status-required');
  requireValue(['cli', 'config', 'profile', 'node', 'journal'].every(name => typeof values[name] === 'string' && values[name].length > 0), 'explicit-connection-and-journal-required');
  const options = {...values, cli: path.resolve(values.cli), config: path.resolve(values.config), journal: path.resolve(values.journal), deadlineSeconds: Number(values['deadline-seconds'])};
  return locked(options.journal, async () => {
    const journal = command === 'plan' ? null : await readJson(options.journal, true);
    const intent = journal?.intent ?? await readJson(path.resolve(values.intent));
    const {client, binding} = await connection(options, intent.tenant);
    if (command === 'plan') {
      const value = await plan(client, intent, binding);
      await durableWrite(options.journal, value, true);
      return {schemaVersion: 'latent.static.route-result.v1', id: value.id, status: 'planned',
        routes: value.rows.map(row => ({id: row.desired.metadata.name, generation: row.baseline.generation,
          publication: row.desired.spec.target.publication}))};
    }
    requireValue(values.intent === undefined, 'journal-intent-is-immutable');
    validateJournal(journal, binding);
    const save = value => durableWrite(options.journal, value);
    if (command === 'status') {
      // Recover receipts and inspect all live state, but never dispatch a write.
      return reconcile(client, journal, save, 0);
    }
    const writes = Number(values['maximum-writes']);
    requireValue(Number.isInteger(writes) && writes >= 1 && writes <= 64, 'write-bound');
    return reconcile(client, journal, save, writes);
  });
}
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    const result = await main(process.argv.slice(2));
    console.log(JSON.stringify(result));
    process.exitCode = ['complete', 'planned'].includes(result.status) ? 0 : result.status === 'uncertain' ? 5 : result.status === 'partial' ? 3 : 4;
  } catch (error) {
    const reason = /^[a-z][a-z-]{0,95}$/.test(error.message) ? error.message : 'route-set-input-or-storage-failed';
    console.log(JSON.stringify({schemaVersion: 'latent.static.route-result.v1', status: 'failed', reason}));
    process.exitCode = 2;
  }
}
