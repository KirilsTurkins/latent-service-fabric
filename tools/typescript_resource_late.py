"""Accepted ordinary timer facilities complete before physical retirement."""
from __future__ import annotations

import json
import subprocess

from tools.phase2_operator_process import require, write_json
from tools.rust_capsule_project import ROOT, digest, read_file

EXPECTED = 'resource-runtime|late=accepted|copies=2|entropy=noncrypto53|wall64=1|fresh=1'
ROOT_LOG = 'resource-ts:late:root-return:timer-accepted'
CALLBACK_LOG = 'resource-ts:late:after-clear:copies=2:entropy=noncrypto53:wall64=1'
ACCOUNTING = ('crates/latent-wasmtime/src/host/logging.rs',
    'crates/latent-wire/src/invocation/trace.rs', 'tools/typescript_guest/console.mjs')
LATE = b'''
  if (mode === 'late') {
    const started = performance.now();
    const timer = setTimeout(() => {
      // This callback is already running. Clearing its timer cannot undo it.
      clearTimeout(timer);
      if (hex(first.bytes) !== '2aff80410d0a' || hex(second.bytes) !== '00ff80410d0a' ||
          first.text !== second.text || first.empty.length !== 0 || second.empty.length !== 0)
        throw new Error('resource-late-independent-copies');
      const value = Math.random();
      if (!Number.isFinite(value) || value < 0 || value >= 1)
        throw new Error('resource-late-approved-noncrypto-entropy');
      if (Date.now() <= 2 ** 32 || performance.now() < started)
        throw new Error('resource-late-full-width-clock');
      console.info('resource-ts:late:after-clear:copies=2:entropy=noncrypto53:wall64=1');
    }, 10);
    console.info('resource-ts:late:root-return:timer-accepted');
    return 'resource-runtime|late=accepted|copies=2|entropy=noncrypto53|wall64=1|fresh=1';
  }
'''


def library_source(original):
    marker = b"  if (mode === 'parallel') {\n"
    require(type(original) is bytes and original.count(marker) == 1
        and b'resource-ts:late:' not in original, 'resource-ts-late-library-preimage')
    return original.replace(marker, LATE + marker, 1)


def log_charge(activation, messages=(ROOT_LOG, CALLBACK_LOG)):
    require(type(activation) is str and activation.isascii() and 1 <= len(activation) <= 128,
        'resource-ts-late-log-activation')
    return sum(len(json.dumps({'activation_id':activation,'level':'info','message':message,
        'fields':{'latent.activation_id':activation,'latent.span_id':'0'*16,'latent.trace_id':'0'*32}},
        separators=(',',':')).encode()) for message in messages)


def accounting_sources(producer):
    rows = {}
    for name in ACCOUNTING:
        current = read_file(ROOT/name, 1024**2)
        original = subprocess.check_output(['git','show',producer+':'+name],cwd=ROOT,timeout=15)
        require(current == original, 'resource-ts-late-original-log-accounting:' + name)
        rows[name] = {'sha256':digest(current),'bytes':len(current)}
    return rows


def accepted(row, budget, revision, component, expected):
    require(row['processReaped'] is True and row['response']['outcomeKnown'] is True
        and row['response']['requestDispatched'] is True
        and row['response']['data']['resolvedRevision'] == revision
        and revision['releaseDigest'] == component, 'resource-ts-late-known-reaped-current')
    usage = row['response']['data']['consumption']
    require(0 < int(usage['cpuFuel']) <= budget['cpuFuel']
        and 0 < int(usage['peakMemoryBytes']) <= budget['memoryBytes']
        and 0 < int(usage['logBytes']) <= budget['logBytes']
        and all(int(usage[key]) == 0 for key in ('outboundRequests','childCalls','effectCount',
            'stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
        'resource-ts-late-original-envelope')
    require(row['exitCode'] == 0 and row['decoded'] == [{'ok':expected}],
        'resource-ts-late-exact-ordinary-result')
    if expected == EXPECTED:
        require(int(usage['logBytes']) == log_charge(row['activation']),
            'resource-ts-late-callback-facilities-must-complete')


def programme(clients, targets, probe, output, component):
    from tools import resource_runtime_node as runtime, typescript_resource_runtime_fixture as fixture
    result = {'status':'incomplete','cases':[],'attempts':[],
        'lateCompletionKind':'accepted ordinary setTimeout after root return path; clear during callback',
        'callbackAfterStoreRetirementClaimed':False,'waitForPollPendingClaimed':False,
        'consoleFlushQueuePresent':False,'cryptographicEntropyClaimed':False,'fullTicketQualification':False}
    for tenant,mode,label in (('examples','late','resource-ts-late-examples'),
        ('foreign','fresh','resource-ts-fresh-after-examples'),
        ('foreign','late','resource-ts-late-foreign'),
        ('examples','fresh','resource-ts-fresh-after-foreign')):
        client,target = clients[tenant],targets[tenant]
        revision = runtime.selected_revision(client,target)
        row = runtime.call(client,target,'resource-runtime','run',[mode],label)
        result['attempts'].append({'tenant':tenant,'mode':mode,'invocation':row})
        (output/'programme-progress.json').write_bytes((json.dumps(result,sort_keys=True,
            separators=(',',':'),allow_nan=False)+'\n').encode())
        accepted(row,target['budget'],revision,component,EXPECTED if mode == 'late' else fixture.EXPECTED['fresh'])
        result['cases'].append({'tenant':tenant,'mode':mode,'invocation':row,
            'retirement':runtime.retire(client,probe,target,output,label)})
    require(len(result['cases']) == 4, 'resource-ts-late-four-actual-outcomes')
    result['status'] = 'passed'
    write_json(output/'programme.json',result)
    return result
