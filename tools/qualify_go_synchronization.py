"""Finite signed Go runtime targets, preserving actual original owners."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_inventory as registry, ci_suite_discovery as discovery
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_project import fresh
from tools.test_run import redact

ROOT = Path(__file__).resolve().parents[1]
CASE = 'runtime::go::synchronization::signed_condition_once_rwmutex_and_channel_ordering_retire_original_v5_owners'
ADMISSION_CASE = 'runtime::go::admission::signed_cross_tenant_cell_saturation_keeps_original_owners_until_cancel_and_trap_retire'
MANAGED_TIMER_CASE = 'runtime::go::managed_timers::signed_managed_v5_timers_gc_callbacks_and_stop_reset_preserve_original_owners'
V7_TIMER_CASE = 'runtime::go::managed_timers::signed_managed_v7_timers_gc_callbacks_and_stop_reset_preserve_original_owners'
TASK_SATURATION_CASE = 'runtime::go::task_saturation::signed_task16_saturation_reports_original_refusal_and_fresh_retirement'
TIMER_OVERLAP_CASE = 'runtime::go::timer_overlap::signed_overlapping_public_timer_operations_retire_the_original_wait'
V7_TIMER_OVERLAP_CASE = 'runtime::go::timer_overlap::signed_v7_overlapping_public_timer_operations_retire_the_original_wait'
FIRED_TIMER_CASE = 'runtime::go::timer_overlap::signed_fired_one_shot_public_stop_and_reset_wait_for_original_next'
ZERO_CLOCK_CASE = 'runtime::go::zero_clock::signed_zero_origin_five_nanosecond_timer_retires_original_wait'
TIMER_MODES = [0, 1, 2, 3, 4, 5, 6, 18, 19, 20, 9, 11, 12, 13, 14, 15, 16, 17]
TIMER_NATIVE_MODES = [mode for mode in TIMER_MODES if mode != 4]
MANAGED_TIMER_ROWS = [('ordinary', iteration, mode, 'success') for iteration in range(2) for mode in TIMER_MODES]
MANAGED_TIMER_ROWS += [('timer-capacity', 0, 8, 'guest-trap'), ('fresh-after-timer-capacity', 0, 0, 'success'),
                       ('callback-failure', 0, 10, 'guest-trap'), ('fresh-after-callback-failure', 0, 0, 'success'),
                       ('cancel-original-root', 0, 7, 'cancelled'), ('deadline-original-root', 0, 7, 'deadline-exceeded'),
                       ('fresh-after-cancel-deadline', 0, 0, 'success')]
QUEUED_CASE = 'runtime::go::queued::signed_ordinary_queue_keeps_original_budgets_deadlines_and_tenant_ownership'
ADMISSION_ROWS = [
    ('warm', 'tenant-a', 'success'), ('warm', 'tenant-b', 'success'),
    ('saturated', 'tenant-b', 'resource-exhausted'), ('foreign-cancel', 'tenant-b', 'not-found'),
    ('original', 'tenant-a', 'cancelled'), ('fresh-after-retirement', 'tenant-b', 'success'),
    ('saturated', 'tenant-a', 'resource-exhausted'), ('foreign-cancel', 'tenant-a', 'not-found'),
    ('original', 'tenant-b', 'guest-trap'), ('fresh-after-retirement', 'tenant-a', 'success'),
    ('final-fresh', 'tenant-a', 'success'), ('final-fresh', 'tenant-b', 'success'),
]
QUEUED_ROWS = [('warm', tenant, 0, 'success') for tenant in ('tenant-a', 'tenant-b')]
for _owner, _peer, _terminal in [('tenant-a', 'tenant-b', 'cancelled'), ('tenant-b', 'tenant-a', 'guest-trap')]:
    QUEUED_ROWS += [('queued-full', _peer, 0, 'pending'),
                    ('saturated', _owner, 0, 'resource-exhausted'),
                    ('foreign-cancel', _owner, 0, 'not-found'),
                    ('queued-cancel', _peer, 0, 'cancelled'),
                    ('replacement-queued', _peer, 0, 'pending'),
                    ('queued-deadline', _peer, 0, 'deadline-exceeded'),
                    ('deadline-replacement', _peer, 0, 'pending'),
                    ('original', _owner, 0, _terminal)]
    QUEUED_ROWS += [('queued-fresh', _peer, index, 'success') for index in range(7)]
QUEUED_ROWS += [('final-fresh', tenant, 0, 'success') for tenant in ('tenant-a', 'tenant-b')]
NATIVE_MODES = [0, 1, 2, 3, 4, 5, 9]
ORDINARY_MODES = [0, 1, 2, 3, 4, 5, 6, 9]
EXTRA = [('blocked-condition', 7, 'guest-trap'), ('fresh-after-blocked', 4, 'success'),
         ('task-exhaustion', 0, 'guest-trap'), ('cancel-original-root', 8, 'cancelled'),
         ('deadline-original-root', 8, 'deadline-exceeded'), ('fresh-after-cancel-deadline', 4, 'success'),
         ('no-checkpoint-startup', 4, 'success'), ('no-checkpoint-spin', 9, 'resource-exhausted'),
         ('no-checkpoint-fresh', 4, 'success')]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def observations(raw: bytes, filtered: int) -> list[dict]:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-synchronization-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-synchronization-exact-signed-case-required')
    rows = [json.loads(value) for value in re.findall(rb'^GO_SYNCHRONIZATION_CASE (.+)$', raw, re.M)]
    expected = [('ordinary', iteration, mode, 'success') for iteration in range(3) for mode in ORDINARY_MODES]
    expected += [(case, 0, mode, outcome) for case, mode, outcome in EXTRA]
    if len(rows) != len(expected):
        raise ValueError('Go-synchronization-missing-or-extra-invocation')
    actual = []
    for row in rows:
        if (set(row) != {'case', 'iteration', 'mode', 'outcome'}
                or type(row['iteration']) is not int or type(row['mode']) is not int):
            raise ValueError('Go-synchronization-private-or-unknown-field')
        actual.append((row['case'], row['iteration'], row['mode'], row['outcome']))
    if actual != expected:
        raise ValueError('Go-synchronization-invocation-contract')
    return rows



def admission_observations(raw: bytes, filtered: int) -> list[dict]:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-admission-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [ADMISSION_CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-admission-exact-signed-case-required')
    rows = [json.loads(value) for value in re.findall(rb'^GO_ADMISSION_CASE (.+)$', raw, re.M)]
    if len(rows) != len(ADMISSION_ROWS):
        raise ValueError('Go-admission-missing-or-extra-observation')
    actual = []
    for row in rows:
        if set(row) != {'case', 'tenant', 'outcome'} or not all(type(value) is str for value in row.values()):
            raise ValueError('Go-admission-private-or-unknown-field')
        actual.append((row['case'], row['tenant'], row['outcome']))
    if actual != ADMISSION_ROWS:
        raise ValueError('Go-admission-observation-contract')
    return rows


def queued_observations(raw: bytes, filtered: int) -> list[dict]:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-queued-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [QUEUED_CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-queued-exact-signed-case-required')
    rows = [json.loads(value) for value in re.findall(rb'^GO_QUEUED_CASE (.+)$', raw, re.M)]
    if len(rows) != len(QUEUED_ROWS):
        raise ValueError('Go-queued-missing-or-extra-observation')
    actual = []
    for row in rows:
        if (set(row) != {'case', 'tenant', 'index', 'outcome'} or type(row['index']) is not int
                or not all(type(row[key]) is str for key in ('case', 'tenant', 'outcome'))):
            raise ValueError('Go-queued-private-or-unknown-field')
        actual.append((row['case'], row['tenant'], row['index'], row['outcome']))
    if actual != QUEUED_ROWS:
        raise ValueError('Go-queued-observation-contract')
    return rows


def managed_timer_observations(raw: bytes, filtered: int, case: str = MANAGED_TIMER_CASE) -> list[dict]:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-managed-timers-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if (case not in {MANAGED_TIMER_CASE, V7_TIMER_CASE} or names != [case.encode()]
            or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]):
        raise ValueError('Go-managed-timers-exact-signed-case-required')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Go-managed-timers-duplicate-field')
            value[key] = item
        return value
    rows = [json.loads(value, object_pairs_hook=unique)
            for value in re.findall(rb'^GO_MANAGED_TIMER_CASE (.+)$', raw, re.M)]
    if len(rows) != len(MANAGED_TIMER_ROWS):
        raise ValueError('Go-managed-timers-missing-or-extra-invocation')
    actual = []
    for row in rows:
        if (set(row) != {'case', 'iteration', 'mode', 'outcome'}
                or type(row['iteration']) is not int or type(row['mode']) is not int
                or type(row['case']) is not str or type(row['outcome']) is not str):
            raise ValueError('Go-managed-timers-private-or-unknown-field')
        actual.append((row['case'], row['iteration'], row['mode'], row['outcome']))
    if actual != MANAGED_TIMER_ROWS:
        raise ValueError('Go-managed-timers-invocation-contract')
    return rows


def task_saturation_observations(raw: bytes, filtered: int) -> dict:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-task-saturation-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [TASK_SATURATION_CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-task-saturation-exact-signed-case-required')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Go-task-saturation-duplicate-field')
            value[key] = item
        return value
    def decode(marker):
        return [json.loads(row, object_pairs_hook=unique) for row in re.findall(
            rb'^' + marker + rb' (.+)$', raw, re.M)]
    rows = decode(b'GO_TASK_SATURATION_CASE')
    markers = re.findall(rb'^(GO_TASK_SATURATION_CASE|GO_TASK_SATURATION_REFUSAL) ', raw, re.M)
    expected = [dict(case=case, outcome=outcome, storesCreated=count, liveStores=0,
                     liveInstances=0, reservations=0, reservedFuel=0, reservedMemory=0)
                for case, outcome, count in [('seven-live', 'success', 1),
                    ('eighth-refused', 'guest-trap', 2), ('fresh-after-refusal', 'success', 3)]]
    refusal = [dict(tenant='tenant-a', activation='go-task16-saturation', stage='execution',
                    reason='runtime-task-limit', configuredBound=16, requestedOwners=17,
                    terminalCauseEstablished=False)]
    # JSON comparison keeps bools, numbers and unknown fields distinct.
    def same(left, right):
        return json.dumps(left, sort_keys=True, separators=(',', ':')) == json.dumps(right, sort_keys=True, separators=(',', ':'))
    if (markers != [b'GO_TASK_SATURATION_CASE', b'GO_TASK_SATURATION_REFUSAL',
                    b'GO_TASK_SATURATION_CASE', b'GO_TASK_SATURATION_CASE']
            or not same(rows, expected) or not same(decode(b'GO_TASK_SATURATION_REFUSAL'), refusal)):
        raise ValueError('Go-task-saturation-original-refusal-or-retirement-required')
    return {'cases': rows, 'refusal': refusal[0]}


def timer_overlap_observations(raw: bytes, diagnostic: bytes, filtered: int, case: str = TIMER_OVERLAP_CASE) -> dict:
    """Require every real case, original-owner retirement, and each witness."""
    if len(raw) > 2 * 1024 * 1024 or len(diagnostic) > 2 * 1024 * 1024:
        raise ValueError('Go-timer-overlap-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if (case not in {TIMER_OVERLAP_CASE, V7_TIMER_OVERLAP_CASE} or names != [case.encode()]
            or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]):
        raise ValueError('Go-timer-overlap-exact-signed-case-required')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Go-timer-overlap-duplicate-field')
            value[key] = item
        return value
    rows = [json.loads(value, object_pairs_hook=unique) for value in
            re.findall(rb'^GO_TIMER_OVERLAP_CASE (.+)$', raw, re.M)]
    expected = [dict(case=case, mode=mode, outcome=outcome, storesCreated=count,
                     liveStores=0, liveInstances=0, reservations=0,
                     reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
                for case, mode, outcome, count in [('reset-reset', 0, 'success', 1),
                    ('reset-stop', 1, 'success', 2), ('gc-reset-reset', 2, 'success', 3),
                    ('gc-reset-stop', 3, 'success', 4), ('cancel-reset-reset', 0, 'cancelled', 5),
                    ('deadline-reset-stop', 1, 'deadline-exceeded', 6), ('fresh', 0, 'success', 7)]]
    if json.dumps(rows, sort_keys=True, separators=(',', ':')) != json.dumps(expected, sort_keys=True, separators=(',', ':')):
        raise ValueError('Go-timer-overlap-signed-retirement-required')
    prefix = b'LSF-GO-TIMER-OVERLAP-V4|'
    records = re.findall(rb'^LSF-GO-TIMER-OVERLAP-V4\|([^\r\n]+)$', diagnostic, re.M)
    if diagnostic.count(prefix) != 6 or len(records) != 6:
        raise ValueError('Go-timer-overlap-exact-witnesses-required')
    observed = []
    names = ('go-timer-overlap-reset-reset', 'go-timer-overlap-reset-stop',
             'go-timer-overlap-gc-reset-reset', 'go-timer-overlap-gc-reset-stop',
             'go-timer-overlap-cancel-reset-reset', 'go-timer-overlap-deadline-reset-stop')
    for case, record in zip(names, records):
        fields = record.split(b'|')
        gc_case = '-gc-' in case
        stop_case = '-cancel-' in case or '-deadline-' in case
        expected_head = [case.encode(), b'1', b'0', b'0', b'4', b'1', b'1', b'1', b'1',
                         b'1' if gc_case else b'0', b'1' if gc_case else b'0', b'1',
                         b'1' if stop_case else b'0']
        if (len(fields) != 15 or fields[:13] != expected_head
                or fields[13] not in ((b'0', b'1') if stop_case else (b'1',))):
            raise ValueError('Go-timer-overlap-causal-witness-required')
        if not re.fullmatch(rb'[1-9][0-9]{0,3}', fields[14]):
            raise ValueError('Go-timer-overlap-witness-budget')
        observed.append({'activation': case, 'postGcMarkerStopped': gc_case, 'handshakeParkObserved': gc_case,
                         'bothParkedBeforeRootStop': stop_case,
                         'returnedBeforeStoreReport': fields[13] == b'1', 'modeledWitnessBytes': int(fields[14])})
    if len({item['modeledWitnessBytes'] for item in observed}) != 1:
        raise ValueError('Go-timer-overlap-inconsistent-layout')
    drop_prefix = b'LSF-GO-TIMER-WAIT-DROP-V1|'
    drops = re.findall(rb'^LSF-GO-TIMER-WAIT-DROP-V1\|([^\r\n|]+)\|([01])$', diagnostic, re.M)
    if diagnostic.count(drop_prefix) != len(names) or len(drops) != len(names):
        raise ValueError('Go-timer-overlap-physical-wait-drops-required')
    drop_map = {name.decode(): returned == b'1' for name, returned in drops}
    if len(drop_map) != len(names) or set(drop_map) != set(names) or not all(drop_map[name] for name in names[:4]):
        raise ValueError('Go-timer-overlap-physical-wait-drops-required')
    return {'cases': rows, 'witnesses': observed,
            'physicalWaitDrops': [{'activation': name, 'returned': drop_map[name]} for name in names]}


def fired_timer_observations(raw: bytes, diagnostic: bytes, filtered: int, *, include_returned_cancel: bool = False) -> dict:
    """Require the matched-token probe and actual original physical drops."""
    if len(raw) > 2 * 1024 * 1024 or len(diagnostic) > 2 * 1024 * 1024:
        raise ValueError('Go-fired-timer-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [FIRED_TIMER_CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-fired-timer-exact-signed-case-required')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Go-fired-timer-duplicate-field')
            value[key] = item
        return value
    prefix = b'GO_TIMER_FIRED_CASE '
    values = re.findall(rb'^GO_TIMER_FIRED_CASE (.+)$', raw, re.M)
    count = 6 if include_returned_cancel else 5
    if raw.count(prefix) != count or len(values) != count:
        raise ValueError('Go-fired-timer-exact-case-count')
    rows = [json.loads(item, object_pairs_hook=unique) for item in values]
    cases = [('stop', 0, 'success', 1), ('reset', 1, 'success', 2),
             ('returned-stop', 2, 'success', 3), ('returned-reset', 3, 'success', 4)]
    if include_returned_cancel:
        cases.append(('returned-cancel', 4, 'cancelled', 5))
    cases.append(('fresh', 0, 'success', 6 if include_returned_cancel else 5))
    expected = [dict(case=case, mode=mode, outcome=outcome, storesCreated=count, liveStores=0,
                     liveInstances=0, reservations=0, reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
                for case, mode, outcome, count in cases]
    if json.dumps(rows, sort_keys=True, separators=(',', ':')) != json.dumps(expected, sort_keys=True, separators=(',', ':')):
        raise ValueError('Go-fired-timer-signed-retirement-required')
    witness_prefix = b'LSF-GO-TIMER-FIRED-V1|'
    records = re.findall(rb'^LSF-GO-TIMER-FIRED-V1\|([^\r\n]+)$', diagnostic, re.M)
    if diagnostic.count(witness_prefix) != 2 or len(records) != 2:
        raise ValueError('Go-fired-timer-exact-witnesses-required')
    ids = ('go-timer-fired-stop', 'go-timer-fired-reset')
    witnesses = []
    for activation, record in zip(ids, records):
        fields = record.split(b'|')
        if len(fields) != 5 or fields[:4] != [activation.encode(), b'1', b'0', b'0']:
            raise ValueError('Go-fired-timer-causal-witness-required')
        if not re.fullmatch(rb'[1-9][0-9]{0,3}', fields[4]):
            raise ValueError('Go-fired-timer-witness-budget')
        witnesses.append({'activation': activation, 'modeledWitnessBytes': int(fields[4])})
    if len({item['modeledWitnessBytes'] for item in witnesses}) != 1:
        raise ValueError('Go-fired-timer-inconsistent-layout')
    returned_prefix = b'LSF-GO-TIMER-RETURNED-V1|'
    returned_records = re.findall(rb'^LSF-GO-TIMER-RETURNED-V1\|([^\r\n]+)$', diagnostic, re.M)
    returned_ids = ('go-timer-returned-stop', 'go-timer-returned-reset')
    if diagnostic.count(returned_prefix) != 2 or len(returned_records) != 2:
        raise ValueError('Go-returned-timer-exact-witnesses-required')
    returned_witnesses = []
    for activation, record in zip(returned_ids, returned_records):
        fields = record.split(b'|')
        if len(fields) != 5 or fields[:4] != [activation.encode(), b'1', b'0', b'0']:
            raise ValueError('Go-returned-timer-causal-witness-required')
        if not re.fullmatch(rb'[1-9][0-9]{0,3}', fields[4]):
            raise ValueError('Go-returned-timer-witness-budget')
        returned_witnesses.append({'activation': activation, 'modeledWitnessBytes': int(fields[4])})
    if any(item['modeledWitnessBytes'] != witnesses[0]['modeledWitnessBytes'] for item in returned_witnesses):
        raise ValueError('Go-returned-timer-inconsistent-layout')
    drop_prefix = b'LSF-GO-TIMER-WAIT-DROP-V1|'
    drops = re.findall(rb'^LSF-GO-TIMER-WAIT-DROP-V1\|([^\r\n|]+)\|([01])$', diagnostic, re.M)
    all_ids = ids + returned_ids + (('go-timer-returned-cancel',) if include_returned_cancel else ())
    if diagnostic.count(drop_prefix) != len(all_ids) or drops != [(name.encode(), b'1') for name in all_ids]:
        raise ValueError('Go-fired-timer-physical-wait-drops-required')
    cancel_prefix = b'LSF-GO-TIMER-RETURNED-CANCEL-V1|'
    cancel_records = re.findall(rb'^LSF-GO-TIMER-RETURNED-CANCEL-V1\|([^\r\n]+)$', diagnostic, re.M)
    result = {'cases': rows, 'witnesses': witnesses, 'returnedWitnesses': returned_witnesses,
              'physicalWaitDrops': [{'activation': name, 'returned': True} for name in all_ids]}
    if include_returned_cancel:
        if diagnostic.count(cancel_prefix) != 1 or len(cancel_records) != 1:
            raise ValueError('Go-returned-cancel-exact-witness-required')
        fields = cancel_records[0].split(b'|')
        if (len(fields) != 5 or fields[:4] != [b'go-timer-returned-cancel', b'1', b'0', b'0']
                or not re.fullmatch(rb'[1-9][0-9]{0,3}', fields[4])
                or int(fields[4]) != witnesses[0]['modeledWitnessBytes']):
            raise ValueError('Go-returned-cancel-causal-witness-required')
        result['returnedCancellationWitness'] = {'activation': 'go-timer-returned-cancel',
            'modeledWitnessBytes': int(fields[4])}
    elif cancel_records or diagnostic.count(cancel_prefix):
        raise ValueError('Go-returned-cancel-unexpected-historical-witness')
    return result


def zero_clock_observations(raw: bytes, diagnostic: bytes, filtered: int) -> dict:
    """Require one admitted timer, its live Wait and the gated 0-to-5 ns edge."""
    if max(len(raw), len(diagnostic)) > 2 * 1024 * 1024:
        raise ValueError('Go-zero-clock-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [ZERO_CLOCK_CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-zero-clock-exact-signed-case-required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Go-zero-clock-duplicate-field')
            result[key] = value
        return result
    rows = [json.loads(value, object_pairs_hook=unique) for value in
            re.findall(rb'^GO_ZERO_CLOCK_CASE (.+)$', raw, re.M)]
    expected = [dict(case='zero-to-five-nanoseconds', outcome='success', rawBefore=0,
                     rawAfter=5, pendingOriginalWait=True, liveStores=0, liveInstances=0,
                     reservations=0, reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)]
    if json.dumps(rows, sort_keys=True, separators=(',', ':')) != json.dumps(expected, sort_keys=True, separators=(',', ':')):
        raise ValueError('Go-zero-clock-signed-retirement-required')
    markers = [line for line in diagnostic.splitlines() if
               line.startswith((b'LSF-GO-NODE-STOP-TIMER-V1|', b'LSF-GO-ZERO-CLOCK-V1|'))]
    if len(markers) != 5:
        raise ValueError('Go-zero-clock-exact-witnesses-required')
    start = markers[0].split(b'|')
    next_event = markers[1].split(b'|')
    root_close = markers[4].split(b'|')
    def valid(fields, event, sequence, waits, timers):
        return (len(fields) == 7 and fields[:4] == [b'LSF-GO-NODE-STOP-TIMER-V1', b'pending', event, sequence]
                and fields[4].isdigit() and 1 <= int(fields[4]) <= 16
                and fields[5:] == [str(waits).encode(), str(timers).encode()])
    if (not valid(start, b'start-accepted', b'1', 0, 1)
            or not valid(next_event, b'next-entered', b'2', 1, 1)
            or markers[2:4] != [b'LSF-GO-ZERO-CLOCK-V1|wait-pending|0|5',
                               b'LSF-GO-ZERO-CLOCK-V1|advance|0|5']
            or not valid(root_close, b'root-close', b'3', 0, 0)):
        raise ValueError('Go-zero-clock-original-wait-order-required')
    return {'cases': rows, 'observations': ['one-timer-accepted', 'one-original-wait-admitted',
            'wait-polled-pending-at-zero', 'same-clock-advanced-five', 'root-closed-with-no-wait-or-timer']}


def campaign(campaign: str, fixture: Path, negative: Path | None) -> dict:
    if campaign == 'synchronization' and negative is not None:
        return {'case': CASE, 'fixture': 'synchronization', 'variable': 'LSF_GO_SYNCHRONIZATION_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v5'), (negative, 'go-component-activation-v1')]}
    if campaign in {'admission', 'queued'} and negative is None:
        return {'case': ADMISSION_CASE if campaign == 'admission' else QUEUED_CASE,
                'fixture': 'managed-idle', 'variable': 'LSF_GO_MANAGED_IDLE_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v5')]}
    if campaign == 'managed-timers' and negative is None:
        return {'case': MANAGED_TIMER_CASE, 'fixture': 'timers', 'variable': 'LSF_GO_MANAGED_TIMER_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v5')]}
    if campaign == 'managed-v7-timers' and negative is None:
        return {'case': V7_TIMER_CASE, 'fixture': 'timers', 'variable': 'LSF_GO_V7_TIMER_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v7')]}
    if campaign == 'task-saturation' and negative is None:
        return {'case': TASK_SATURATION_CASE, 'fixture': 'task-saturation', 'variable': 'LSF_GO_TASK_SATURATION_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v5')]}
    if campaign == 'timer-overlap' and negative is None:
        return {'case': TIMER_OVERLAP_CASE, 'fixture': 'timer-overlap', 'variable': 'LSF_GO_TIMER_OVERLAP_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v5')]}
    if campaign == 'timer-overlap-v7' and negative is None:
        return {'case': V7_TIMER_OVERLAP_CASE, 'fixture': 'timer-overlap', 'variable': 'LSF_GO_V7_TIMER_OVERLAP_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v7')]}
    if campaign == 'zero-clock-v7' and negative is None:
        return {'case': ZERO_CLOCK_CASE, 'fixture': 'zero-clock', 'variable': 'LSF_GO_V7_ZERO_CLOCK_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v7')]}
    if campaign == 'timer-fired-v7' and negative is None:
        return {'case': FIRED_TIMER_CASE, 'fixture': 'timer-fired', 'variable': 'LSF_GO_V7_TIMER_FIRED_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v7')]}
    raise ValueError('Go-runtime-unreviewed-campaign-or-negative')


def source_snapshot(root: Path) -> dict:
    files = {path for folder in ('sdk/go-guest', 'tools/go_guest')
             for path in (root / folder).rglob('*') if path.is_file() and '__pycache__' not in path.parts}
    files |= {root / name for name in ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', '.cargo/managed-guest.toml',
              'crates/latent-wasmtime/Cargo.toml', 'crates/latent-wasmtime/tests/local_service.rs',
              'crates/latent-wasmtime/tests/local_service/runtime.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/zero_clock.rs',
              'crates/latent-wasmtime/tests/local_service/zero_clock.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/synchronization.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/admission.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/queued.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/managed_timers.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/task_saturation.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/timer_overlap.rs',
              'crates/latent-wasmtime/tests/local_service/fixture.rs',
              'crates/latent-wasmtime/tests/guest_sdk/runtime.rs',
              'crates/latent-wasmtime/tests/local_service/packages.rs',
              'crates/latent-wasmtime/tests/local_service/component.rs',
              'crates/latent-core/src/activation_runtime.rs', 'crates/latent-core/src/activation_runtime/timer.rs',
              'crates/latent-core/src/test_support/clocks.rs', 'crates/latent-core/src/clock.rs',
              'crates/latent-executor/src/preparation_read_wait.rs',
              'crates/latent-node/src/activation_manager/control.rs',
              'crates/latent-wasmtime/src/host/clock.rs',
              'crates/latent-wasmtime/src/host/runtime/positive_timer_observer.rs',
              'crates/latent-core/src/budget.rs', 'crates/latent-core/src/budget/descendants/mod.rs',
              'crates/latent-capabilities/src/broker.rs', 'crates/latent-capabilities/src/broker/session.rs',
              'crates/latent-wasmtime/src/host/runtime.rs', 'crates/latent-wasmtime/src/lib.rs',
              'crates/latent-wasmtime/src/backend.rs', 'crates/latent-wasmtime/src/development_go_timer_cancel.rs',
              'crates/latent-wasmtime/src/development_go_timer_overlap.rs', 'crates/latent-wasmtime/src/development_go_timer_fired_state.rs', 'wit/platform/activation-runtime/package.wit',
              '.github/workflows/go-guest.yml',
              '.github/workflows/go-synchronization-reference.yml', 'tools/ci/suites.json',
              'tools/tests/test_go_task_saturation.py', 'tools/tests/test_go_timer_overlap.py', 'tools/tests/test_go_fired_timer.py',
              'tools/tests/go_fired_fence_controls.py',
              'tools/tests/test_go_managed_timers.py', 'tools/tests/test_go_zero_clock.py',
              'tools/stage_runtime_wit.py',
              'tools/qualify_go_activation.py', 'tools/qualify_go_synchronization.py')}
    if len(files) > 1024:
        raise ValueError('Go-synchronization-source-count')
    rows = {}
    for path in sorted(files):
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Go-synchronization-source-file')
        rows[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return rows


def compile_identity(path: Path, root: Path, profile: str, fixture: str = 'synchronization') -> dict:
    raw = (path / 'GO-ACTIVATION-COMPILE.json').read_bytes()
    if len(raw) > 512 * 1024:
        raise ValueError('Go-synchronization-compiler-receipt-bound')
    record = json.loads(raw)
    if (fixture not in {'synchronization', 'managed-idle', 'timers', 'task-saturation', 'timer-overlap', 'timer-fired', 'zero-clock'}
            or (fixture in {'managed-idle', 'task-saturation'} and profile != 'go-component-activation-v5')
            or (fixture == 'timer-overlap' and profile not in {'go-component-activation-v5', 'go-component-activation-v7'})
            or (fixture == 'timer-fired' and profile != 'go-component-activation-v7')
            or (fixture == 'zero-clock' and profile != 'go-component-activation-v7')
            or (fixture == 'timers' and profile not in {'go-component-activation-v5', 'go-component-activation-v7'})
            or (fixture == 'synchronization' and profile not in {'go-component-activation-v1', 'go-component-activation-v5'})):
        raise ValueError('Go-runtime-unreviewed-source-profile')
    folder = {'synchronization': 'synchronization-conformance', 'managed-idle': 'managed-idle-conformance',
              'timers': 'timers-conformance', 'task-saturation': 'task-saturation-conformance',
              'timer-overlap': 'timer-overlap-conformance', 'timer-fired': 'timer-fired-conformance',
              'zero-clock': 'zero-clock-conformance'}[fixture]
    source = (root / 'sdk/go-guest/runtime' / folder / 'main.go').read_bytes()
    if (record['profile'] != profile or record['fixture'] != fixture
            or record['sourceDigest'] != 'sha256:' + digest(source) or record['sourceUnchanged'] is not True
            or record['ordinarySource'] is not True or record['signedExecution'] != 'not-run'
            or (path / 'src/main.go').read_bytes() != source):
        raise ValueError('Go-synchronization-compiler-source-or-profile')
    if ((fixture in {'task-saturation', 'timer-overlap', 'timer-fired', 'zero-clock'} or
            (fixture == 'timers' and profile == 'go-component-activation-v7')) and (path / 'wit/world.wit').read_bytes()
            != (root / 'sdk/go-guest/runtime' / folder / 'world.wit').read_bytes()):
        raise ValueError('Go-' + fixture + '-compiler-world')
    component = path / 'build/component.wasm'
    if component.is_symlink() or component.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Go-synchronization-component-bound')
    if record['componentDigest'] != 'sha256:' + digest(component.read_bytes()):
        raise ValueError('Go-synchronization-component-identity')
    if profile in {'go-component-activation-v5', 'go-component-activation-v7'}:
        native = record['nativeReference']
        expected_modes = {'synchronization': NATIVE_MODES, 'managed-idle': [0, 1, 2], 'timers': TIMER_NATIVE_MODES,
                          'task-saturation': [0], 'timer-overlap': [0, 1, 2, 3],
                          'timer-fired': [0, 1, 2, 3], 'zero-clock': [0]}[fixture]
        native_outputs = (native.get('outputs') in ([42, 42, 42, 42], [42, 43, 42, 42],
                                                    [42, 42, 42, 43], [42, 43, 42, 43])
                          if fixture == 'timer-overlap' else native.get('output') == 42)
        if (native['modes'] != expected_modes or not native_outputs
                or native['freshProcessPerMode'] is not True or native['sourceDigest'] != record['sourceDigest']):
            raise ValueError('Go-synchronization-native-reference')
    if fixture == 'timer-fired':
        from tools.go_guest.fired_timer_witness import (derive, derive_bridge, derive_activation_bridge,
            GO_CHAN_SHA256, GO_RUNTIME2_SHA256)
        original_timer = (root / 'sdk/go-guest/runtime/timer_async.go.in').read_bytes()
        original_bridge = (root / 'sdk/go-guest/runtime/timer_bridge.go.in').read_bytes()
        original_activation = (root / 'sdk/go-guest/runtime/activation_bridge.go.in').read_bytes()
        derived_timer, derived_bridge, derived_activation = (derive(original_timer),
            derive_bridge(original_bridge), derive_activation_bridge(original_activation))
        diagnostic_timer = path / 'diagnostic-sdk/runtime/timer_async.go.in'
        diagnostic_bridge = path / 'diagnostic-sdk/runtime/timer_bridge.go.in'
        diagnostic_activation = path / 'diagnostic-sdk/runtime/activation_bridge.go.in'
        runtime_chan = path / 'diagnostic-runtime-inputs/runtime/chan.go'
        runtime_descriptor = path / 'diagnostic-runtime-inputs/runtime/runtime2.go'
        if (runtime_chan.is_symlink() or runtime_descriptor.is_symlink()
                or runtime_chan.stat().st_size > 128 * 1024 or runtime_descriptor.stat().st_size > 128 * 1024
                or digest(runtime_chan.read_bytes()) != GO_CHAN_SHA256
                or digest(runtime_descriptor.read_bytes()) != GO_RUNTIME2_SHA256
                or diagnostic_timer.is_symlink() or diagnostic_timer.read_bytes() != derived_timer
                or diagnostic_bridge.is_symlink() or diagnostic_bridge.read_bytes() != derived_bridge
                or diagnostic_activation.is_symlink() or diagnostic_activation.read_bytes() != derived_activation
                or record.get('diagnosticRuntime') != {'kind': 'selected-returned-ticker-cancel-fence-observe-v4',
                    'originalTimerAsyncDigest': 'sha256:' + digest(original_timer),
                    'derivedTimerAsyncDigest': 'sha256:' + digest(derived_timer),
                    'originalTimerBridgeDigest': 'sha256:' + digest(original_bridge),
                    'derivedTimerBridgeDigest': 'sha256:' + digest(derived_bridge),
                    'originalActivationBridgeDigest': 'sha256:' + digest(original_activation),
                    'derivedActivationBridgeDigest': 'sha256:' + digest(derived_activation),
                    'runtimeChanDigest': 'sha256:' + GO_CHAN_SHA256,
                    'runtimeDescriptorDigest': 'sha256:' + GO_RUNTIME2_SHA256}):
            raise ValueError('Go-fired-timer-diagnostic-runtime-drift')
    identity = {'receiptSha256': digest(raw), 'profile': profile, 'sourceDigest': record['sourceDigest'],
                'componentDigest': record['componentDigest'], 'bindingDigest': record['bindingDigest'],
                'toolMaterialsSha256': digest(json.dumps(record['tools'], sort_keys=True).encode()),
                'transformationsSha256': digest(json.dumps(record['transformations'], sort_keys=True).encode()),
                'nativeReference': record.get('nativeReference')}
    if fixture == 'timer-fired':
        identity['diagnosticRuntime'] = record['diagnosticRuntime']
    return identity


def qualify(root: Path, output: Path, fixture: Path, negative: Path | None, revision: str, programme: str = 'synchronization') -> dict:
    if sys.platform != 'linux':
        raise ValueError('Go-synchronization-Linux-owned-execution-required')
    plan = campaign(programme, fixture, negative)
    environment = {**os.environ, 'CARGO_BUILD_JOBS': '2', 'CARGO_INCREMENTAL': '0',
                   'LSF_GUEST_SDK_LANGUAGE': 'go', plan['variable']: str(fixture.resolve())}
    if negative is not None:
        environment['LSF_GO_SYNCHRONIZATION_NO_CHECKPOINT_FIXTURE'] = str(negative.resolve())
    if programme == 'zero-clock-v7':
        environment['LSF_GO_NODE_STOP_TIMER_OBSERVER'] = '1'
    artifacts.require_source(root, revision, environment)
    def clean_source():
        state = run_owned(['git', '-c', 'gc.auto=0', 'status', '--porcelain'], cwd=root,
                          env=environment, timeout=30, maximum=65536)
        if state.returncode or state.output.strip():
            raise ValueError('Go-synchronization-uncommitted-source')
    clean_source()
    before = source_snapshot(root)
    material = {profile: compile_identity(path, root, profile, plan['fixture']) for path, profile in plan['inputs']}
    suites = registry.load(root / 'tools/ci/suites.json')['suites']
    suite, = [row for row in suites if row['id'] == 'latent-wasmtime.test.local-service']
    if plan['case'] not in suite['expectedIgnored'] or suite['timeoutSeconds'] != 900:
        raise ValueError('Go-synchronization-suite-contract')
    output = fresh(output)
    features = ['--features', 'development-go-timer-overlap'] if programme in {'timer-overlap', 'timer-overlap-v7', 'timer-fired-v7'} else []
    command = ['cargo', '--config', '.cargo/managed-guest.toml', 'test', '--locked', '-p', 'latent-wasmtime',
               '--test', 'local_service', *features, plan['case'], '--', '--ignored', '--exact', '--show-output']
    deadline = time.monotonic() + 1800
    list_base = ['cargo', '--config', '.cargo/managed-guest.toml', 'test', '--locked',
                 '-p', 'latent-wasmtime', '--test', 'local_service', *features, '--']
    discovered = []
    for label, arguments in (("all", ["--list"]), ("ignored", ["--ignored", "--list"])):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Go-synchronization-signed-command-deadline')
        observed = run_owned([*list_base, *arguments], cwd=root, env=environment,
                             timeout=remaining, maximum=2 * 1024 * 1024, separate_stderr=True)
        (output / (label + '-list.stdout.log')).write_bytes(observed.output)
        (output / (label + '-list.stderr.log')).write_bytes(redact(observed.stderr.decode('utf-8', 'replace')).encode())
        if observed.returncode:
            raise ValueError('Go-synchronization-list-command-failed')
        discovered.append(discovery.listing(observed.output))
    available, ignored = discovered
    discovery.validate_cases(suite, available, ignored, {})
    if programme == 'managed-v7-timers':
        active = sorted(available - ignored)
        if not active:
            raise ValueError('Go-v7-timers-active-negative-control-missing')
        try:
            discovery.validate_cases(suite, available, ignored | {active[0]}, {})
        except registry.InventoryError:
            pass
        else:
            raise ValueError('Go-v7-timers-added-skip-was-accepted')
    if plan['case'] not in ignored:
        raise ValueError('Go-synchronization-required-case-missing')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError('Go-synchronization-signed-command-deadline')
    try:
        result = run_owned(command, cwd=root, env=environment, timeout=remaining,
                           maximum=2 * 1024 * 1024, separate_stderr=True)
    except ProcessFailure as error:
        if error.result is not None:
            (output / 'signed.stdout.log').write_bytes(error.result.output)
            (output / 'signed.stderr.log').write_bytes(redact(error.result.stderr.decode('utf-8', 'replace')).encode())
        raise
    (output / 'signed.stdout.log').write_bytes(result.output)
    (output / 'signed.stderr.log').write_bytes(redact(result.stderr.decode('utf-8', 'replace')).encode())
    if result.returncode:
        raise ValueError('Go-synchronization-signed-command-failed')
    parser = {'synchronization': observations, 'admission': admission_observations,
              'queued': queued_observations, 'managed-timers': managed_timer_observations,
              'managed-v7-timers': managed_timer_observations,
              'task-saturation': task_saturation_observations, 'timer-overlap': None, 'timer-overlap-v7': None,
              'timer-fired-v7': None, 'zero-clock-v7': None}[programme]
    if programme in {'timer-overlap', 'timer-overlap-v7'}:
        observed = timer_overlap_observations(result.output, result.stderr, len(available) - 1, plan['case'])
    elif programme == 'timer-fired-v7':
        observed = fired_timer_observations(result.output, result.stderr, len(available) - 1,
                                            include_returned_cancel=True)
    elif programme == 'managed-v7-timers':
        observed = managed_timer_observations(result.output, len(available) - 1, V7_TIMER_CASE)
    elif programme == 'zero-clock-v7':
        observed = zero_clock_observations(result.output, result.stderr, len(available) - 1)
    else:
        observed = parser(result.output, len(available) - 1)
    rows = observed['cases'] if programme in {'task-saturation', 'timer-overlap', 'timer-overlap-v7', 'timer-fired-v7', 'zero-clock-v7'} else observed
    after = source_snapshot(root)
    after_material = {profile: compile_identity(path, root, profile, plan['fixture']) for path, profile in plan['inputs']}
    clean_source()
    if before != after or material != after_material:
        raise ValueError('Go-synchronization-source-or-component-changed')
    receipt = {'schemaVersion': {'synchronization': 'lsf.go-synchronization-reference.v1',
                                 'admission': 'lsf.go-admission-reference.v1',
                                 'queued': 'lsf.go-queued-reference.v1',
                                 'managed-timers': 'lsf.go-managed-timers-reference.v1',
                                 'managed-v7-timers': 'lsf.go-managed-v7-timers-reference.v1',
                                 'task-saturation': 'lsf.go-task-saturation-reference.v1',
                                 'timer-overlap': 'lsf.go-timer-overlap-reference.v4',
                                 'timer-overlap-v7': 'lsf.go-v7-timer-overlap-reference.v1',
                                 'timer-fired-v7': 'lsf.go-v7-fired-timer-reference.v1',
                                 'zero-clock-v7': 'lsf.go-v7-zero-clock-reference.v1'}[programme], 'sourceRevision': revision,
               'sourceBefore': before, 'sourceAfter': after, 'compilerInputsBefore': material,
               'compilerInputsAfter': after_material, 'case': plan['case'], 'signedCases': rows,
               'signedInvocations': {'synchronization': len(rows), 'admission': 8, 'queued': 20,
                                     'managed-timers': len(rows), 'managed-v7-timers': len(rows),
                                     'task-saturation': 3, 'timer-overlap': 7, 'timer-overlap-v7': 7, 'timer-fired-v7': len(rows), 'zero-clock-v7': len(rows)}[programme], 'guestTaskCeiling': 16,
               'managedCapacity': 8, 'waitCeiling': 4, 'newRuntimeProfile': False,
               'kernelTlsOrCrossTenantQualified': False, 'fullGoRuntimeQualified': False}
    if programme == 'synchronization':
        receipt['limitedTaskCeiling'] = 10
    elif programme in {'admission', 'queued'}:
        receipt.update({'signedObservationCount': len(rows), 'admissionRefusals': 2, 'foreignCancellationControls': 2,
                        'physicalCells': 1, 'nodeAdmissionCeiling': 1 if programme == 'admission' else 8,
                        'tenantsShareManagerBackendAndCell': True,
                        'generalSchedulerFairnessQualified': False,
                        'auxiliaryCallee': {'kind': 'synthetic-handwritten-wasm-encoder',
                                            'constructor': 'packages::callee(42)', 'invoked': False,
                                            'sources': ['crates/latent-wasmtime/tests/local_service/packages.rs',
                                                        'crates/latent-wasmtime/tests/local_service/component.rs']}})
        if programme == 'queued':
            receipt.update({'nodeQueueCeiling': 8, 'observedMaximumQueued': 7,
                            'queuedCancellationBeforeStore': 2, 'queuedDeadlineBeforeStore': 2,
                            'rootDeadlineIncludesQueueWaiting': True,
                            'aggregateCpuAndMemoryCeilingsUnchanged': True})
    elif programme in {'managed-timers', 'managed-v7-timers'}:
        receipt.update({'timerCeiling': 2, 'signedObservationCount': 43,
                        'nativeReferenceModes': TIMER_NATIVE_MODES,
                        'relabelsLegacyV3Evidence': False, 'fullTimerRaceMatrixQualified': False})
        if programme == 'managed-v7-timers':
            receipt.update({'profile': 'go-component-activation-v7', 'queuedWorkCeiling': 16,
                            'addedSkipNegativeRejected': True, 'relabelsV5Evidence': False,
                            'fullAggregateGoCostsQualified': False})
    elif programme == 'zero-clock-v7':
        receipt.update({'profile': 'go-component-activation-v7', 'queuedWorkCeiling': 16,
                        'timerCeiling': 2, 'manualClockAndWaitAreTestInfrastructure': True,
                        'providerObservations': observed['observations'],
                        'fullTimerRaceMatrixQualified': False, 'kernelRetirementQualified': False})
    elif programme == 'task-saturation':
        receipt.update({'originalTaskLimitObservation': observed['refusal'], 'liveApplicationWorkersBeforeRefusal': 7,
                        'terminalCauseEstablishedByObservation': False,
                        'fullAggregateGoCostsQualified': False, 'kernelRetirementQualified': False})
    else:
        receipt.update({'originalTimerOverlapWitnesses': observed['witnesses'],
                        'physicalTimerWaitDrops': observed['physicalWaitDrops'], 'timerCeiling': 2,
                        'developmentWitnessOnly': True, 'fullTimerRaceMatrixQualified': False,
                        'fullAggregateGoCostsQualified': False, 'kernelRetirementQualified': False})
        if programme == 'timer-fired-v7':
            receipt.update({'profile': 'go-component-activation-v7', 'queuedWorkCeiling': 16,
                            'returnedTimerWitnesses': observed['returnedWitnesses'],
                            'returnedCancellationWitness': observed['returnedCancellationWitness'],
                            'diagnosticGuestOverlay': True, 'byteIdenticalProductionGuest': False})
        if programme == 'timer-overlap-v7':
            receipt.update({'profile': 'go-component-activation-v7', 'queuedWorkCeiling': 16,
                            'relabelsV5Evidence': False})
    raw = (json.dumps(receipt, indent=2) + '\n').encode()
    if len(raw) > 262144:
        raise ValueError('Go-synchronization-receipt-bound')
    (output / 'receipt.json').write_bytes(raw)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--no-checkpoints', type=Path)
    parser.add_argument('--campaign', choices=('synchronization', 'admission', 'queued', 'managed-timers', 'managed-v7-timers', 'task-saturation', 'timer-overlap', 'timer-overlap-v7', 'timer-fired-v7', 'zero-clock-v7'), default='synchronization')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args()
    qualify(ROOT, args.output, args.fixture, args.no_checkpoints, args.source_commit, args.campaign)
    print('Actual signed Go ' + args.campaign + ' and original-owner controls passed; full #742 remains open')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
