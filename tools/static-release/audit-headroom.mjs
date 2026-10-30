#!/usr/bin/env node
// Advisory planning only: no mutation, reservation, audit append, or replay.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseArgs} from 'node:util';
import {readJson} from './io.mjs';
import {requireValue} from './model.mjs';
import {auditHeadroom, humanHeadroom, inventoryHeadroom} from './audit-capacity.mjs';
export {auditHeadroom, humanHeadroom, inventoryHeadroom} from './audit-capacity.mjs';

export async function main(argv) {
  const {values, positionals} = parseArgs({args: argv, allowPositionals: true, strict: true, options: {
    usage: {type: 'string'}, 'audit-config': {type: 'string'}, inventory: {type: 'string'}, node: {type: 'string'},
    output: {type: 'string', default: 'json'},
    'route-pairs': {type: 'string', default: '1'}, 'diagnostic-records': {type: 'string', default: '2'},
    'competing-operations': {type: 'string', default: '1'}, 'warning-percent': {type: 'string', default: '80'},
    'cadence-minutes': {type: 'string', default: '10'},
  }});
  const fromInventory = values.inventory && values.node && !values.usage && !values['audit-config'];
  const fromUsage = values.usage && values['audit-config'] && !values.inventory && !values.node;
  requireValue(positionals.length === 0 && (fromInventory || fromUsage)
    && ['json', 'human'].includes(values.output), 'audit-headroom-input-required');
  const number = key => {
    requireValue(/^(0|[1-9][0-9]{0,8})$/.test(values[key]), 'audit-planning-option-bound');
    return Number(values[key]);
  };
  const options = {routePairs: number('route-pairs'), diagnosticRecords: number('diagnostic-records'),
    competingOperations: number('competing-operations'), warningPercent: number('warning-percent'),
    cadenceMinutes: number('cadence-minutes')};
  let report;
  if (fromInventory) {
    const envelope = await readJson(path.resolve(values.inventory), true);
    report = inventoryHeadroom(envelope, values.node, options);
  } else {
    const envelope = await readJson(path.resolve(values.usage), true);
    const audit = await readJson(path.resolve(values['audit-config']), true);
    const usage = envelope?.schemaVersion === 'latent.cli.result.v1' && envelope.category === 'success'
      && envelope.outcomeKnown === true ? envelope.data?.nodeUsage : null;
    report = auditHeadroom(usage, audit, options);
  }
  return {report, output: values.output === 'human' ? humanHeadroom(report) : JSON.stringify(report)};
}
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    const {report, output} = await main(process.argv.slice(2));
    console.log(output);
    process.exitCode = {'headroom-observed': 0, warning: 3, blocked: 4, unavailable: 5}[report.status];
  } catch {
    console.log(JSON.stringify({schemaVersion: 'latent.static.audit-headroom.v1', advisory: true,
      reservation: false, executionPermission: false, sampleFreshness: 'not-established',
      filesystemCapacity: 'not-observed', historyComplete: false,
      status: 'unavailable', reasons: ['audit-headroom-input-or-storage-failed']}));
    process.exitCode = 2;
  }
}
