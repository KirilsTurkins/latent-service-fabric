"""Temporary exact-source candidate preparation; never updates a branch."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ALLOWED = {
    'crates/latent-wire/src/management/capabilities/conversion.rs',
    'apps/latent/src/management/phase2/projection/capability.rs',
    'apps/latent/src/error/details.rs', 'apps/latent/src/error.rs',
    'apps/latent/src/error/audit_tests.rs', 'tools/ci/suites.json',
}


def replace(name, before, after):
    path = Path(name)
    text = path.read_text()
    if after in text:
        return
    if text.count(before) != 1:
        raise SystemExit('candidate-context-mismatch:' + name)
    path.write_text(text.replace(before, after))


def prepare():
    wire = 'crates/latent-wire/src/management/capabilities/conversion.rs'
    replace(wire, 'if let Some(audit) = value.audit {', '''if let Some(audit) = value.audit {
        result.counters.insert(
            "audit_previous_session_loss_unknown".into(),
            u64::from(audit.previous_session_loss_unknown),
        );''')
    replace(wire, '            dropped_observations,\n            unavailable_events,', '            retained_records,\n            retained_bytes,\n            unknown_outcomes,\n            dropped_observations,\n            unavailable_events,')
    replace(wire, '                queued_bytes: 16 * 1024,', '                retained_records: 4096,\n                retained_bytes: 4_299_161,\n                unknown_outcomes: 2,\n                previous_session_loss_unknown: true,\n                queued_bytes: 16 * 1024,')
    replace(wire, '        assert_eq!(encoded.counters["audit_queued_operations"], 0);', '''        assert_eq!(encoded.counters["audit_retained_records"], 4096);
        assert_eq!(encoded.counters["audit_retained_bytes"], 4_299_161);
        assert_eq!(encoded.counters["audit_unknown_outcomes"], 2);
        assert_eq!(encoded.counters["audit_previous_session_loss_unknown"], 1);
        assert_eq!(encoded.counters["audit_queued_operations"], 0);''')
    projection = 'apps/latent/src/management/phase2/projection/capability.rs'
    replace(projection, '        "capture_dropped"\n            | "closed"', '        "capture_dropped"\n            | "retained_records"\n            | "retained_bytes"\n            | "unknown_outcomes"\n            | "previous_session_loss_unknown"\n            | "closed"')
    replace('apps/latent/src/error/details.rs', '    Some(match kind {', '''    Some(match kind {
        "audit-journal" => &[("reason", Known(&[
            "audit-capacity", "audit-critical-pending", "audit-busy",
            "audit-unavailable", "audit-closed", "audit-corrupt",
        ]))],''')
    replace('apps/latent/src/error.rs', 'mod details;', 'mod details;\n#[cfg(test)]\nmod audit_tests;')
    path = Path('tools/ci/suites.json')
    data = json.loads(path.read_text())
    additions = {
        ('latent-audit', 'lib'): [
            'durable::diagnostics::tests::known_reason_survives_without_claiming_mutation_disposition',
            'durable::diagnostics::tests::unrecognized_text_is_not_a_public_diagnostic'],
        ('latent', 'lib'): [
            'error::audit_tests::audit_reasons_are_closed_and_never_disclose_peer_text',
            'error::audit_tests::audit_diagnostics_preserve_known_rejection_and_transport_uncertainty'],
    }
    for (package, kind), cases in additions.items():
        rows = [row for row in data['suites'] if row.get('package') == package and row.get('kind') == kind]
        if len(rows) != 1:
            raise SystemExit('ambiguous-suite-owner:' + package)
        row = rows[0]
        added = set(cases) - set(row['expectedCases'])
        row['expectedCases'] = sorted(set(row['expectedCases']) | set(cases))
        row['minimumCases'] += len(added)
        print('REGISTERED', row['id'], sorted(added))
    path.write_text(json.dumps(data, indent=2) + '\n')


def publish():
    changed = set(subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines())
    if not changed <= ALLOWED:
        raise SystemExit('unexpected-candidate-change:' + repr(sorted(changed - ALLOWED)))
    receipt = {'source': os.environ['GITHUB_SHA'], 'files': {}}
    for name in sorted(changed):
        raw = Path(name).read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise SystemExit('candidate-byte-bound')
        body = json.dumps({'content': base64.b64encode(raw).decode(), 'encoding': 'base64'}).encode()
        request = urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/git/blobs', data=body,
            headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            receipt['files'][name] = json.load(response)['sha']
    Path(os.environ['RUNNER_TEMP'], 'audit-candidates.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('AUDIT_CANDIDATES=' + json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['publish']:
        publish()
    else:
        raise SystemExit('explicit-candidate-operation-required')
