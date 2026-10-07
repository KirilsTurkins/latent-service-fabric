"""Source-bound projection of the original invocation only; no runtime authority."""
from __future__ import annotations

import re

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools.dev_workflow import node_diagnostics
from tools.dev_workflow.common import digest, encode, require, sha

SCHEMA = 'lsf.guest.compatibility.outcomes.v1'
ERROR_CODES = frozenset({'ok', 'cancelled', 'unknown', 'deadline-exceeded', 'unimplemented', 'internal',
    'unavailable', 'data-loss', 'out-of-range', 'resource-exhausted', 'invalid-argument', 'not-found',
    'already-exists', 'permission-denied', 'unauthenticated', 'failed-precondition', 'aborted',
    *node_diagnostics.TRAP_CODES})
DIAGNOSTIC_FIELDS = frozenset({'stage', 'reason', 'profile', 'profile_digest', 'configured_bound',
    'calculated_requirement', 'fixed_bytes', 'lifting_fuel', 'lift_multiplier'})


def from_build(source, descriptor, receipt):
    """Read sidecars beside already-verified component bytes; no backend query."""
    from pathlib import Path
    from tools.dev_workflow import paths
    try:
        capture = Capture(receipt['source'], receipt['artifacts']['component'])
    except (ValueError, KeyError, TypeError):
        return None  # No authenticated build identity; never invent one.
    parent = Path(descriptor['artifacts']['component']).parent
    name = str(parent / 'compatibility-context.json').replace('\\', '/')
    if not (source / name).exists() and not (source / name).is_symlink():
        return capture
    try:
        report = compatibility.read(paths.read(source, str(parent / 'compatibility-report.json').replace('\\', '/'), compatibility.MAX_BYTES))
        original_source = paths.read(source, str(parent / 'source-inputs.json').replace('\\', '/'), 8 * 1024 * 1024)
        selected = context.read(paths.read(source, name, context.MAX_BYTES), report=report,
                                source=digest(original_source), component=capture.component)
        runtime = selected['standardRuntime']
        if runtime['state'] == 'selected-unqualified':
            owner_runtime = runtime.get('receiptName') == 'standard-runtime-selection.json'
            raw = paths.read(source, str(parent / runtime.get('receiptName', 'runtime-profile.json')).replace('\\', '/'),
                             65536 if owner_runtime else 4 * 1024 * 1024)
            require(digest(raw) == runtime['receiptDigest'], 'compatibility-outcomes-stale-runtime')
            if owner_runtime:
                from tools import guest_runtime_receipts
                owner = guest_runtime_receipts.read(raw, language=selected['language'], source=digest(original_source),
                    component=capture.component, profile=runtime['profile'])
                require(owner['ownerIssue'] == runtime.get('ownerIssue'), 'compatibility-outcomes-stale-runtime-owner')
        for material in selected['materials']:
            if material['name'] == 'automatic-compiler-patches':
                raw = paths.read(source, str(parent / 'compiler-patches.json').replace('\\', '/'), 4 * 1024 * 1024)
                require(digest(raw) == material['digest'], 'compatibility-outcomes-stale-patch')
        capture.context, capture.context_state = selected, 'observed'
    except (ValueError, OSError, TypeError, KeyError):
        capture.context_state = 'invalid-present'
    return capture


def diagnostic(error):
    details = error.get('details') if isinstance(error, dict) else None
    if details is None:
        return {'state': 'absent'}
    if not isinstance(details, list) or len(details) > 16:
        return {'state': 'invalid-present'}
    rows = [row for row in details if isinstance(row, dict) and row.get('kind') == 'activation.diagnostic.v1']
    if not rows:
        return {'state': 'absent'}
    if len(rows) != 1:
        return {'state': 'invalid-present'}
    fields = rows[0].get('fields')
    if not isinstance(fields, dict) or not {'stage', 'reason'} <= fields.keys() or not fields.keys() <= DIAGNOSTIC_FIELDS:
        return {'state': 'invalid-present'}
    retained = {}
    for name, value in fields.items():
        if name == 'profile_digest':
            if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
                return {'state': 'invalid-present'}
            retained[name] = value
            continue
        if not isinstance(value, str) or re.fullmatch('0|[1-9][0-9]{0,19}', value) is None or int(value) >= 2**64:
            return {'state': 'invalid-present'}
        if name in {'stage', 'reason', 'profile'} and not 1 <= int(value) <= {'stage': 8, 'reason': 16, 'profile': 2}[name]:
            return {'state': 'invalid-present'}
        retained[name] = value
    return {'state': 'observed', 'fields': retained}


def original(value):
    projected = node_diagnostics.original_result(value)
    error = value.get('error') if isinstance(value, dict) else None
    if error is None:
        projected['errorCodeState'] = 'absent'
    elif isinstance(error, dict) and isinstance(error.get('code'), str) and error['code'] in ERROR_CODES:
        projected.update(errorCodeState='observed', errorCode=error['code'])
    else:
        projected['errorCodeState'] = 'invalid-present'
    observed = diagnostic(error)
    projected['activationDiagnostic'] = observed
    projected['cause'] = 'unknown'
    projected['resourceDimension'] = 'unknown'
    # The node-owned numeric observation has a closed meaning. A coarse gRPC
    # code, trap, QueuePressure or success cannot identify a library operation.
    if observed['state'] == 'observed':
        reason = int(observed['fields']['reason'])
        if reason in {5, 8, 10, 11, 13, 14, 15}:
            projected['cause'] = {5: 'missing-provider', 8: 'denied-grant', 10: 'resource-exhausted',
                11: 'resource-exhausted', 13: 'deadline', 14: 'deadline', 15: 'cancelled'}[reason]
        if reason in {10, 11}:
            projected['resourceDimension'] = {10: 'guest-memory', 11: 'fuel'}[reason]
    projected['libraryReachability'] = 'unknown'
    projected['physicalRetirement'] = 'unproven'
    return projected


class Capture:
    """Finite diagnostic sidecar; never a retry, status query or execution ledger."""
    def __init__(self, frontend_source: str, component: str, selected_context=None):
        self.source, self.component = sha(frontend_source), sha(component)
        self.context, self.context_state = None, 'absent'
        if selected_context is not None:
            try:
                self.context = context.validate(selected_context, component=component)
                self.context_state = 'observed'
            except (ValueError, TypeError, KeyError):
                self.context_state = 'invalid-present'
        self.rows, self.bytes, self.omitted = [], 0, 0

    def observe(self, case, value, client_reaped, *, expected_revision=None):
        if not isinstance(case, str) or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', case) is None:
            self.omitted += 1
            return
        row = {'case': case, **original(value), 'clientProcess': 'reaped' if client_reaped is True else 'not-confirmed'}
        # Target selection was already checked by the invocation owner. This
        # observation does not replace that check or infer it from HTTP success.
        if expected_revision is not None:
            actual = value.get('data', {}).get('resolvedRevision') if isinstance(value, dict) and isinstance(value.get('data'), dict) else None
            row['targetMatches'] = isinstance(actual, dict) and actual == expected_revision
        size = len(encode(row))
        if len(self.rows) >= node_diagnostics.MAX_CASES or self.bytes + size > node_diagnostics.MAX_BYTES - 4096:
            self.omitted += 1
            return
        self.rows.append(row); self.bytes += size

    def snapshot(self):
        value = {'schemaVersion': SCHEMA, 'frontendSourceDigest': self.source, 'componentDigest': self.component,
                 'contextState': self.context_state,
                 'cases': list(self.rows), 'omittedCases': self.omitted, 'authority': 'none',
                 'libraryReachability': 'unknown', 'initialization': 'unknown', 'workerDrain': 'unproven',
                 'retrySafety': 'unknown'}
        if self.context is not None:
            value.update(contextIdentity=self.context['identity'], compatibilitySourceDigest=self.context['sourceDigest'],
                         compatibilityReportIdentity=self.context['compatibilityReportIdentity'])
        value['identity'] = digest(encode(value))
        require(len(encode(value)) <= node_diagnostics.MAX_BYTES, 'compatibility-outcomes-byte-limit')
        return value
