"""Accepted ordinary Java/.NET callbacks finish facilities after cancel/dispose.

The callback remains inside its live activation. No post-Store callback or
asynchronous Console/PrintStream flush worker is inferred from these rows.
"""
from __future__ import annotations

import json
import subprocess

from tools.dotnet_http_mixed_node import natural
from tools.phase2_operator_process import require
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import call, sample, selected_revision
from tools.rust_capsule_project import ROOT, digest, read_file, write_json

COMMON = '|readers=2|binary=00ff80410d0a|text=1|empty=1|entropy=8|wall64=1|closed=1'
EXPECTED = {
    'java': {'late': 'resource-late|cancel=false|entered=1|completed=1'+COMMON,
             'fresh': 'resource-late|fresh'+COMMON},
    'dotnet': {'late': 'resource-late|dispose=pending|entered=1|completed=1'+COMMON,
               'fresh': 'resource-late|fresh'+COMMON},
}
ACCOUNTING = ('crates/latent-wasmtime/src/host/logging.rs',
              'crates/latent-wire/src/invocation/trace.rs')
LIMITS = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
          'timers': 8, 'results': 8, 'nativeOwners': 8}


def accounting_sources(producer):
    rows = {}
    for name in ACCOUNTING:
        current = read_file(ROOT/name, 1024**2)
        original = subprocess.check_output(['git', 'show', producer+':'+name], cwd=ROOT, timeout=15)
        require(current == original, 'resource-late-frozen-log-accounting:'+name)
        rows[name] = {'sha256': digest(original), 'bytes': len(original)}
    return rows


def log_charge(activation, marker):
    require(type(activation) is str and activation.isascii() and 1 <= len(activation) <= 32
        and marker in ('L', 'F'), 'resource-late-fixed-completion-record')
    # Both ordinary stdout bridges emit info with no application fields. The
    # frozen host adds exactly these trusted 32/16-hex correlation identities.
    value = {'activation_id': activation, 'level': 'info', 'message': marker,
        'fields': {'latent.activation_id': activation, 'latent.span_id': '0'*16,
                   'latent.trace_id': '0'*32}}
    return len(json.dumps(value, separators=(',', ':')).encode('ascii'))


def checked(row, language, mode, budget, component, revision):
    require(language in EXPECTED and mode in EXPECTED[language], 'resource-late-closed-programme')
    response = row['response']; usage = response['data']['consumption']
    require(row['processReaped'] is True and row['exitCode'] == 0
        and response['outcomeKnown'] is True and response['requestDispatched'] is True
        and response['category'] == 'success' and response['data']['resolvedRevision'] == revision
        and revision['releaseDigest'] == component
        and row['decoded'] == [{'ok': EXPECTED[language][mode]}], 'resource-late-exact-signed-result')
    require(0 < natural(usage['cpuFuel']) <= budget['cpuFuel']
        and 0 < natural(usage['peakMemoryBytes']) <= budget['memoryBytes']
        and natural(usage['logBytes']) == log_charge(row['activation'], 'L' if mode == 'late' else 'F')
        and natural(usage['logBytes']) <= budget['logBytes']
        and all(natural(usage[name]) == 0 for name in ('outboundRequests', 'childCalls', 'effectCount',
            'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes')),
        'resource-late-original-budget-exact-callback-log-no-other-effects')


def retired(client, probe, target, output, label):
    usage = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']
    node = usage['nodeUsage']
    require(usage['nextPageToken'] is None and type(node) is dict and node['scope'] == 'node'
        and type(node['unavailable']) is list and node['unavailable'] == []
        and type(node['counters']) is dict
        and all(natural(node['counters'][name]) == 0 for name in ACTIVE_COUNTERS),
        'resource-late-all-eighteen-active-provider-owners-zero')
    physical = sample(client, probe, label+'-retired', 2)
    value = {'provider': node, 'physical': physical}
    write_json(output/('retired-'+label+'.json'), value)
    return value


def programme(clients, targets, probe, output, component, language):
    require(language in EXPECTED, 'resource-late-supported-language')
    prefix = 'j' if language == 'java' else 'n'
    record = {'status': 'incomplete', 'cases': [], 'attempts': [],
        'lateCompletionKind': 'entered ordinary TimerTask cancel(false)' if language == 'java'
            else 'entered ordinary Timer callback with incomplete self-DisposeAsync',
        'callbackAfterStoreRetirementClaimed': False, 'nativeWaitPendingClaimed': False,
        'consoleFlushQueuePresent': False, 'fullTicketQualification': False}

    def checkpoint():
        (output/'programme-progress.json').write_bytes((json.dumps(record, sort_keys=True,
            separators=(',', ':'), allow_nan=False)+'\n').encode())

    for tenant, mode, suffix in (('examples', 'late', 'l-a'), ('foreign', 'fresh', 'f-b'),
            ('foreign', 'late', 'l-b'), ('examples', 'fresh', 'f-a')):
        client, target = clients[tenant], targets[tenant]; label = prefix+suffix
        pin = selected_revision(client, target)
        try:
            row = call(client, target, 'greeting', 'greet', ['resource-runtime:'+mode], label)
            record['attempts'].append({'tenant': tenant, 'mode': mode, 'invocation': row}); checkpoint()
            checked(row, language, mode, target['budget'], component, pin)
            record['cases'].append({'tenant': tenant, 'mode': mode, 'invocation': row,
                'retirement': retired(client, probe, target, output, label)})
            checkpoint()
        except BaseException as error:
            record.update(status='failed', failedTenant=tenant, failedMode=mode,
                errorCategory=type(error).__name__)
            checkpoint()
            raise
    require(len(record['cases']) == 4, 'resource-late-four-actual-late-and-fresh-outcomes')
    record.update(status='passed', sameNode=True, singleExecutionCell=True,
        lateAfterCancelOrDisposeBeforePhysicalRetirement=True)
    write_json(output/'programme.json', record)
    return record
