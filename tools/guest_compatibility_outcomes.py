"""Source-bound projection of the original invocation only; no runtime authority."""
from __future__ import annotations

import re

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools.dev_workflow import node_diagnostics
from tools.dev_workflow.common import decode, digest, encode, integer, members, require, sha

SCHEMA = 'lsf.guest.compatibility.outcomes.v1'
MAX_BYTES = node_diagnostics.MAX_BYTES
ERROR_CODES = frozenset({'ok', 'cancelled', 'unknown', 'deadline-exceeded', 'unimplemented', 'internal',
    'unavailable', 'data-loss', 'out-of-range', 'resource-exhausted', 'invalid-argument', 'not-found',
    'already-exists', 'permission-denied', 'unauthenticated', 'failed-precondition', 'aborted',
    *node_diagnostics.TRAP_CODES})
DIAGNOSTIC_FIELDS = frozenset({'stage', 'reason', 'profile', 'profile_digest', 'configured_bound',
    'calculated_requirement', 'fixed_bytes', 'lifting_fuel', 'lift_multiplier'})
# Labels for latent-core's producer-owned ActivationDiagnostic vocabulary.
# These describe its observation, not an inferred library failure or remedy.
DIAGNOSTIC_LABELS = {
    'stage': {1: 'admission', 2: 'queue', 3: 'preparation', 4: 'binding', 5: 'execution',
              6: 'provider', 7: 'cleanup', 8: 'output-validation'},
    'reason': {1: 'signature-allocation-limit', 2: 'value-allocation-limit',
        3: 'unsupported-component-surface', 4: 'unsupported-engine-profile',
        5: 'provider-absent', 6: 'binding-absent', 7: 'admission-denied', 8: 'grant-denied',
        9: 'queue-pressure', 10: 'guest-memory-exhausted', 11: 'guest-fuel-exhausted',
        12: 'guest-resource-exhausted', 13: 'provider-timeout', 14: 'deadline-exceeded',
        15: 'cancelled', 16: 'http-response-rejected'},
    'profile': {1: 'wasmtime-service-values-v1', 2: 'wasmtime-buffered-web-values-v1'},
}
DIAGNOSTIC_MEASUREMENTS = ('configured_bound', 'calculated_requirement', 'fixed_bytes',
                           'lifting_fuel', 'lift_multiplier')
CAUSES = {5: 'missing-provider', 8: 'denied-grant', 10: 'resource-exhausted',
          11: 'resource-exhausted', 12: 'resource-exhausted', 13: 'deadline', 14: 'deadline', 15: 'cancelled'}


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
        if name in DIAGNOSTIC_LABELS and int(value) not in DIAGNOSTIC_LABELS[name]:
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
        projected['cause'] = CAUSES.get(reason, 'unknown')
        if reason in {10, 11}:
            projected['resourceDimension'] = {10: 'guest-memory', 11: 'fuel'}[reason]
    projected['libraryReachability'] = 'unknown'
    projected['physicalRetirement'] = 'unproven'
    return projected


def validate(value, *, report=None, selected_context=None):
    members(value, {'schemaVersion', 'frontendSourceDigest', 'componentDigest', 'contextState',
        'cases', 'omittedCases', 'authority', 'libraryReachability', 'initialization', 'workerDrain',
        'retrySafety', 'identity'}, {'contextIdentity', 'compatibilitySourceDigest', 'compatibilityReportIdentity'})
    require(value['schemaVersion'] == SCHEMA, 'compatibility-outcomes-version')
    for key in ('frontendSourceDigest', 'componentDigest', 'identity'):
        sha(value[key])
    require(isinstance(value['contextState'], str) and value['contextState'] in {'absent', 'invalid-present', 'observed'},
            'compatibility-outcomes-context-state')
    links = {'contextIdentity', 'compatibilitySourceDigest', 'compatibilityReportIdentity'}
    require((links <= value.keys()) if value['contextState'] == 'observed' else not links & value.keys(),
            'compatibility-outcomes-context-links')
    for key in links & value.keys():
        sha(value[key])
    require((value['authority'], value['libraryReachability'], value['initialization'],
             value['workerDrain'], value['retrySafety']) == ('none', 'unknown', 'unknown', 'unproven', 'unknown'),
            'compatibility-outcomes-cannot-certify-support-or-retirement')
    require(isinstance(value['cases'], list) and len(value['cases']) <= node_diagnostics.MAX_CASES,
            'compatibility-outcomes-case-limit')
    integer(value['omittedCases'], 0, 2**64 - 1)
    for row in value['cases']:
        members(row, {'case', 'errorCodeState', 'activationDiagnostic', 'cause', 'resourceDimension',
            'libraryReachability', 'physicalRetirement', 'clientProcess'},
            {'malformed', 'category', 'outcomeKnown', 'consumption', 'invalidConsumptionFields',
             'guestTrapCode', 'trapDetailsUnavailable', 'admissionCurrentnessReason', 'errorCode', 'targetMatches',
             'guestTrapKind', 'guestRuntimePhase', 'trapKindUnavailable'})
        require(isinstance(row['case'], str)
                and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', row['case']) is not None,
                'compatibility-outcomes-case-name')
        require(isinstance(row['errorCodeState'], str) and row['errorCodeState'] in {'absent', 'invalid-present', 'observed'},
                'compatibility-outcomes-error-state')
        require(('errorCode' in row) == (row['errorCodeState'] == 'observed'), 'compatibility-outcomes-error-code')
        if 'errorCode' in row:
            require(isinstance(row['errorCode'], str) and row['errorCode'] in ERROR_CODES,
                    'compatibility-outcomes-error-code')
        observed = members(row['activationDiagnostic'], {'state'}, {'fields'})
        require(isinstance(observed['state'], str) and observed['state'] in {'absent', 'invalid-present', 'observed'},
                'compatibility-outcomes-diagnostic-state')
        require(('fields' in observed) == (observed['state'] == 'observed'), 'compatibility-outcomes-diagnostic-fields')
        if observed['state'] == 'observed':
            require(diagnostic({'details': [{'kind': 'activation.diagnostic.v1', 'fields': observed['fields']}]}) == observed,
                    'compatibility-outcomes-diagnostic-fields')
        reason = int(observed['fields']['reason']) if observed['state'] == 'observed' else None
        require(row['cause'] == CAUSES.get(reason, 'unknown')
                and row['resourceDimension'] == {10: 'guest-memory', 11: 'fuel'}.get(reason, 'unknown'),
                'compatibility-outcomes-cause-evidence')
        require((row['libraryReachability'], row['physicalRetirement']) == ('unknown', 'unproven')
                and isinstance(row['clientProcess'], str) and row['clientProcess'] in {'reaped', 'not-confirmed'},
                'compatibility-outcomes-retirement-evidence')
        if 'guestTrapKind' in row:
            require(node_diagnostics.valid_trap_kind(row['guestTrapKind'], row.get('guestTrapCode'),
                    row.get('guestRuntimePhase')) and 'trapKindUnavailable' not in row
                    and ('guestRuntimePhase' not in row or isinstance(row['guestRuntimePhase'], str)),
                    'compatibility-outcomes-trap-kind-evidence')
        else:
            require('guestRuntimePhase' not in row, 'compatibility-outcomes-trap-kind-evidence')
        if 'trapKindUnavailable' in row:
            require(row['trapKindUnavailable'] is True and 'guestTrapCode' in row,
                    'compatibility-outcomes-trap-kind-evidence')
        for key in ('outcomeKnown', 'targetMatches'):
            if key in row:
                require(type(row[key]) is bool, 'compatibility-outcomes-boolean')
        for key in ('malformed', 'trapDetailsUnavailable'):
            if key in row:
                require(row[key] is True, 'compatibility-outcomes-boolean')
        if 'category' in row:
            require(isinstance(row['category'], str) and row['category'] in node_diagnostics.CATEGORIES,
                    'compatibility-outcomes-category')
        if 'consumption' in row:
            counters = members(row['consumption'], set(), set(node_diagnostics.U64_FIELDS + node_diagnostics.U32_FIELDS))
            for name, number in counters.items():
                bits = 64 if name in node_diagnostics.U64_FIELDS else 32
                require(isinstance(number, str) and node_diagnostics._decimal(number, 64) == number and int(number) < 1 << bits,
                        'compatibility-outcomes-consumption')
        if 'invalidConsumptionFields' in row:
            names = row['invalidConsumptionFields']
            require(isinstance(names, list) and len(names) <= len(node_diagnostics.U64_FIELDS + node_diagnostics.U32_FIELDS)
                    and all(isinstance(name, str)
                    and name in node_diagnostics.U64_FIELDS + node_diagnostics.U32_FIELDS for name in names)
                    and len(names) == len(set(names)) and not set(names) & row.get('consumption', {}).keys(),
                    'compatibility-outcomes-invalid-consumption')
        if 'guestTrapCode' in row:
            require(isinstance(row['guestTrapCode'], str) and row['guestTrapCode'] in node_diagnostics.TRAP_CODES
                    and row.get('errorCode') == 'guest-trap' and 'trapDetailsUnavailable' not in row,
                    'compatibility-outcomes-trap-code')
        if 'trapDetailsUnavailable' in row:
            require(row.get('errorCode') == 'guest-trap', 'compatibility-outcomes-trap-code')
        if 'admissionCurrentnessReason' in row:
            require(isinstance(row['admissionCurrentnessReason'], str)
                    and row['admissionCurrentnessReason'] in node_diagnostics.CURRENTNESS_REASONS
                    and row.get('guestTrapCode') == 'guest-runtime-error', 'compatibility-outcomes-currentness')
    require(len(encode(value)) <= MAX_BYTES
            and digest(encode({key: item for key, item in value.items() if key != 'identity'})) == value['identity'],
            'compatibility-outcomes-identity-or-size')
    if report is not None:
        compatibility.validate(report)
        require(value['componentDigest'] == report['componentDigest'], 'compatibility-outcomes-stale-component')
        if value['contextState'] == 'observed':
            require(value['compatibilitySourceDigest'] == report['sourceDigest']
                    and value['compatibilityReportIdentity'] == report['identity'], 'compatibility-outcomes-stale-report')
    if selected_context is not None:
        context.validate(selected_context, report=report, component=value['componentDigest'])
        if value['contextState'] == 'observed':
            require((value['contextIdentity'], value['compatibilitySourceDigest'], value['compatibilityReportIdentity']) ==
                    (selected_context['identity'], selected_context['sourceDigest'], selected_context['compatibilityReportIdentity']),
                    'compatibility-outcomes-stale-context')
    return value


def read(raw, **bindings):
    return validate(decode(raw, MAX_BYTES), **bindings)


def present(value):
    validate(value)
    lines = [f"Original invocation outcomes: {len(value['cases'])} retained; context {value['contextState']}."]
    for row in value['cases']:
        dimension = f" ({row['resourceDimension']})" if row['resourceDimension'] != 'unknown' else ''
        code = row.get('errorCode', row['errorCodeState'])
        lines.append(f"{row['case']}: cause {row['cause']}{dimension}; code {code}; client {row['clientProcess']}.")
        if 'guestTrapCode' in row:
            lines.append(f"Observed runtime disposition {row['guestTrapCode']}.")
        if 'guestTrapKind' in row:
            lines.append(f"Observed engine trap kind {row['guestTrapKind']}.")
        if 'guestRuntimePhase' in row:
            lines.append(f"Observed runtime phase {row['guestRuntimePhase']}.")
        observed = row['activationDiagnostic']
        if observed['state'] == 'observed':
            fields = observed['fields']
            labels = [f"{name} {DIAGNOSTIC_LABELS[name][int(fields[name])]} ({fields[name]})"
                      for name in DIAGNOSTIC_LABELS if name in fields]
            lines.append('Observed node diagnostic: ' + '; '.join(labels) + '.')
            measurements = [f'{name} {fields[name]}' for name in DIAGNOSTIC_MEASUREMENTS if name in fields]
            if measurements:
                lines.append('Observed node measurements: ' + '; '.join(measurements) + '.')
        else:
            lines.append(f"Node diagnostic: {observed['state']}.")
        if row.get('targetMatches') is False:
            lines.append('Selected target differs from the original invocation result.')
    if value['omittedCases']:
        lines.append(f"Additional invocation observations omitted: {value['omittedCases']}.")
    lines.append('Library reachability and initialization remain unknown; physical retirement is unproven. No retry right is inferred.')
    return '\n'.join(lines) + '\n'


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
