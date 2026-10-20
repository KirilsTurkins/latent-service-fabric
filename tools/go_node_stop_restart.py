"""Respect the original authority's persisted anti-rollback floor before reopen.

This is a test-driver ordering barrier, not a startup retry or lease renewal.
The normal native authority independently verifies the same floor on startup.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

from tools.phase2_operator_process import require
from tools.phase2_operator_scenario import connect
from tools.rust_capsule_project import read_file, write_json


def _unique(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'Go-node-stop-restart-floor-duplicate-field')
        result[name] = value
    return result


def _seconds():
    value = time.time_ns()
    require(type(value) is int and 0 < value < (1 << 64) * 1000000000,
            'Go-node-stop-restart-clock')
    return value // 1000000000


def restart(client, binary, directory, config, tenant, ordinal, evidence):
    original = client.deadline
    deadline = min(original, time.monotonic() + 30)  # Existing startup watchdog.
    path = Path(directory) / 'data/supply-chain/floor.json'
    record = {'status': 'in-progress', 'qualification': False,
        'source': 'original-stopped-node-durable-authority-floor', 'startupAttempts': 0,
        'originalStartupWatchdogMillis': 30000, 'authorityMutated': False}
    node = None
    try:
        raw = read_file(path, 4096)
        value = json.loads(raw, object_pairs_hook=_unique)
        require(type(value) is dict and set(value) == {'formatVersion', 'epoch', 'restartNotBefore', 'policy'}
                and type(value['formatVersion']) is int and value['formatVersion'] == 1
                and type(value['policy']) is dict
                and all(type(value[key]) is int and 0 < value[key] < 1 << 64
                        for key in ('epoch', 'restartNotBefore')),
                'Go-node-stop-restart-floor-shape')
        floor, epoch = value['restartNotBefore'], value['epoch']
        now = _seconds()
        require(floor <= now + 5, 'Go-node-stop-restart-floor-outside-native-lease')
        record.update(authorityEpoch=epoch, restartNotBeforeUnixSeconds=floor,
            observedAtUnixSeconds=now, waitRequired=now < floor)
        # Never spawn a doomed replacement inside the old durable lease. This
        # consumes the SAME startup deadline; no failure is retried or ignored.
        while now < floor:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'Go-node-stop-restart-floor-deadline')
            time.sleep(min(0.025, remaining))
            current = _seconds()
            require(current >= now, 'Go-node-stop-restart-clock-regressed')
            now = current
        require(read_file(path, 4096) == raw, 'Go-node-stop-restart-floor-changed')
        remaining = int(deadline - time.monotonic())
        require(remaining >= 1, 'Go-node-stop-restart-floor-deadline')
        record.update(readyAtUnixSeconds=now, startupAttempts=1)
        client.deadline = deadline
        node = connect(client, binary, directory, config, tenant, ordinal,
            startup_timeout=min(30, remaining), control_refusal_diagnostic=True)
        record['status'] = 'started'
        return node, record
    except BaseException:
        record['status'] = 'failed'
        raise
    finally:
        client.deadline = original
        try:
            write_json(evidence, record)
        except BaseException:
            if node is not None:
                client.node = None
                node.close()
            raise
