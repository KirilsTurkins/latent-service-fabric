"""Bounded, read-only host observations after a failed signed Fetch case.

These counters are diagnostics, not proof of native/Store physical retirement.
The original invocation exception remains the outcome even if observation fails.
"""
from contextlib import contextmanager
import re
import time

from tools.phase2_operator_process import write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_node import NODE_ID


def failed_case_observation(client, target, output, name):
    """Take at most two reads, sharing the original campaign's remaining time."""
    receipt = {'schemaVersion': 'latent.typescript.fetch-failure-observation.v1',
               'case': name, 'scope': 'post-failure-host-counters-only',
               'physicalRetirementProven': False, 'observations': {}}
    if re.fullmatch(r'[a-z0-9-]{1,64}', name) is None:
        return {'status': 'unavailable', 'reason': 'invalid-case-name',
                'physicalRetirementProven': False}
    deadline = min(client.deadline, time.monotonic() + 3)
    reads = (
        ('inventory', ('node', 'get', NODE_ID), 'inventory'),
        ('providerUsage', ('capability', 'list', '--deployment', target['name'],
                           '--include-node-usage'), 'nodeUsage'),
    )
    for label, command, field in reads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            receipt['observations'][label] = {'status': 'unavailable', 'reason': 'deadline'}
            continue
        try:
            # A failed or unknown read is unavailable. Explicit codes prevent
            # uncertain operations from invoking additional audit fallbacks.
            row = client.call(*command, timeout=remaining, codes=(0, 2, 3, 4, 5, 6, 130))
            if row.get('category') != 'success' or row.get('outcomeKnown') is not True:
                raise ValueError('failed-observation-read')
            value = row['data'][field]
            receipt['observations'][label] = {'status': 'observed', 'value': value}
        except Exception:
            # Never copy exception text, retry an invocation or manufacture zeros.
            receipt['observations'][label] = {'status': 'unavailable', 'reason': 'read-failed'}
    receipt['status'] = ('observed' if all(row['status'] == 'observed'
                         for row in receipt['observations'].values()) else 'partial')
    path = output / ('after-failed-' + name + '.json')
    try:
        write_json(path, receipt)
        identity = file_identity(path)
    except Exception:
        return {'status': 'unavailable', 'reason': 'evidence-write-failed',
                'physicalRetirementProven': False}
    return {'status': receipt['status'], 'path': path.name,
            'identity': identity, 'physicalRetirementProven': False}


@contextmanager
def observe_case_failure(client, target, output, name, result):
    """Preserve the exact original failure, including when diagnostics fail."""
    try:
        yield
    except Exception:
        try:
            observation = failed_case_observation(client, target, output, name)
        except Exception:
            observation = {'status': 'unavailable', 'reason': 'observation-failed',
                           'physicalRetirementProven': False}
        result['failedCase'] = {'name': name, 'cleanupObservation': observation}
        raise
