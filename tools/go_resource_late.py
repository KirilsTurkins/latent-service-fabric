"""Ordinary resource facilities in a callback which Stop can no longer prevent.

This is a finite component programme, not evidence from a scheduling model.
No callback after Store retirement or wait-for Poll::Pending is claimed.
"""
from __future__ import annotations

import json
import subprocess

from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file, write_json

EXPECTED = 'resource-go|late=stopped-false|readers=2|entropy=8|wall64=1|fresh=1'
ROOT_LOG = b'resource-go:late:root-return:callback-still-accepted\n'
CALLBACK_LOG = b'resource-go:late:after-stop-false:readers=2:entropy=8:wall64=1\n'
LOG_ACCOUNTING = ('crates/latent-wasmtime/src/host/logging.rs',
    'crates/latent-wire/src/invocation/trace.rs', 'sdk/go-guest/runtime/standard_log.go.in')
LATE = b'''
func lateFacilities() string {
    log.SetFlags(0)
    log.SetPrefix("")
    first, second := data.Open(), data.Open()
    var prefix [2]byte
    if n, err := io.ReadFull(first, prefix[:]); n != 2 || err != nil || prefix != [2]byte{0,255} {
        panic("late first reader prefix changed")
    }
    gate, entered := make(chan struct{}), make(chan struct{})
    started := time.Now()
    timer := time.AfterFunc(time.Millisecond, func() {
        defer func() {
            if first.Close() != nil || second.Close() != nil { panic("late reader close failed") }
        }()
        close(entered)
        <-gate
        if read(first) != "80410d0a" || read(second) != "00ff80410d0a" {
            panic("late independent resource positions changed")
        }
        var entropy [8]byte
        if n, err := rand.Read(entropy[:]); n != 8 || err != nil { panic("late entropy failed") }
        if time.Now().UnixMilli() <= 1<<32 || time.Since(started) < 0 { panic("late clock changed") }
        logged("resource-go:late:after-stop-false:readers=2:entropy=8:wall64=1")
    })
    <-entered
    if timer.Stop() { panic("running callback was falsely reported stopped") }
    logged("resource-go:late:root-return:callback-still-accepted")
    // The accepted callback owns both readers. Closing the gate does not join
    // or erase that work: the original compiler/runtime finish must drain it.
    defer close(gate)
    return "resource-go|late=stopped-false|readers=2|entropy=8|wall64=1|fresh=1"
}
'''


def library_source(original: bytes) -> bytes:
    marker = b'    data.Check()\n'
    require(type(original) is bytes and original.count(marker) == 1
            and b'func lateFacilities(' not in original, 'resource-late-source-preimage')
    return original.replace(marker, marker + b'    if mode == "late" { return lateFacilities() }\n', 1) + LATE


def log_charge(activation, messages=(ROOT_LOG, CALLBACK_LOG)):
    # Frozen357e host/logging.rs BorrowedLog charges compact encoded JSON,
    # including trusted correlation. invocation/trace.rs generates 32/16 hex
    # IDs, so their unknown values do not change the encoded byte lengths.
    require(type(activation) is str and activation.isascii()
            and 1 <= len(activation) <= 128, 'resource-late-log-activation')
    return sum(len(json.dumps({'activation_id': activation, 'level': 'error',
        'message': message.decode('ascii'), 'fields': {
            'latent.activation_id': activation, 'latent.span_id': '0' * 16,
            'latent.trace_id': '0' * 32}}, separators=(',', ':')).encode()) for message in messages)


def accounting_sources(producer):
    sources = {}
    for name in LOG_ACCOUNTING:
        current = read_file(ROOT / name, 1024**2)
        original = subprocess.check_output(['git', 'show', producer + ':' + name], cwd=ROOT, timeout=15)
        require(current == original, 'resource-late-frozen-log-accounting-source:' + name)
        sources[name] = {'sha256': digest(original), 'bytes': len(original)}
    return sources


def accepted(row, budget, revision, component, expected):
    require(row['processReaped'] is True and row['response']['outcomeKnown'] is True
            and row['response']['requestDispatched'] is True
            and row['response']['data']['resolvedRevision'] == revision
            and revision['releaseDigest'] == component, 'resource-late-current-known-reaped')
    usage = row['response']['data']['consumption']
    require(0 < int(usage['cpuFuel']) <= budget['cpuFuel']
            and 0 < int(usage['peakMemoryBytes']) <= budget['memoryBytes']
            and 0 < int(usage['logBytes']) <= budget['logBytes']
            and all(int(usage[key]) == 0 for key in ('outboundRequests', 'childCalls', 'effectCount',
                'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes')),
            'resource-late-original-envelope-no-other-effects')
    require(row['exitCode'] == 0 and row['decoded'] == [{'ok': expected}],
            'resource-late-ordinary-callback-and-fresh-result')
    if expected == EXPECTED:
        # The root log alone cannot satisfy this exact original-budget charge.
        # Only the source-bound callback logs after all facility assertions.
        require(int(usage['logBytes']) == log_charge(row['activation']),
                'resource-late-callback-log-must-complete-before-result')


def programme(clients, targets, probe, output, component):
    from tools import go_resource_runtime_fixture as fixture, resource_runtime_node as runtime
    _fixture, _scalars, _limits, template, function, prefix = runtime.selection('go')
    result = {'status': 'incomplete', 'cases': [], 'attempts': [],
        'lateCompletionKind': 'ordinary AfterFunc already entered; Stop(false) retains accepted callback',
        'callbackAfterStoreRetirementClaimed': False, 'waitForPollPendingClaimed': False,
        'consoleFlushQueuePresent': False, 'fullTicketQualification': False}
    for tenant, mode, label in (
        ('examples', 'late', 'resource-late-examples'),
        ('foreign', 'fresh', 'resource-fresh-after-late-examples'),
        ('foreign', 'late', 'resource-late-foreign'),
        ('examples', 'fresh', 'resource-fresh-after-late-foreign')):
        client, target = clients[tenant], targets[tenant]
        revision = runtime.selected_revision(client, target)
        row = runtime.call(client, target, template, function, [prefix + mode], label)
        result['attempts'].append({'tenant': tenant, 'mode': mode, 'invocation': row})
        write_json(output / 'programme-progress.json', result)
        expected = EXPECTED if mode == 'late' else fixture.EXPECTED['fresh']
        accepted(row, target['budget'], revision, component, expected)
        result['cases'].append({'tenant': tenant, 'mode': mode, 'invocation': row,
            'retirement': runtime.retire(client, probe, target, output, label)})
        write_json(output / 'programme-progress.json', result)
    require(len(result['cases']) == 4, 'resource-late-four-admitted-outcomes')
    result['status'] = 'passed'
    write_json(output / 'programme.json', result)
    return result
