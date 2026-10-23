"""Temporary bounded candidate builder. Never creates a commit or moves a ref."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

STORE = 'crates/latent-audit/src/durable/store.rs'
ROOT = 'crates/latent-audit/src/durable/store/lifecycle'
RUST = [STORE, 'crates/latent-audit/src/durable.rs', STORE[:-3] + '/io.rs', STORE[:-3] + '/query.rs',
        ROOT + '.rs', *[ROOT + '/' + name + '.rs' for name in ['model', 'storage', 'rollover', 'transfer', 'tests']]]
ALLOWED = set(RUST) | {'tools/ci/suites.json'}
CASES = [
    'full_epoch_rollover_preserves_bytes_and_global_sequence',
    'rollover_cutpoints_resume_original_identity_without_reset',
    'pending_attempts_and_live_owners_block_maintenance_and_unknown_stays_unknown',
    'full_custody_requires_verified_oldest_transfer_before_another_rollover',
    'transfer_cutpoints_keep_custody_until_the_destination_is_reverified',
    'corrupt_and_missing_sealed_history_is_not_repaired_or_deleted',
    'a_sealed_staging_archive_with_missing_history_blocks_capacity_release',
    'private_path_and_archive_identity_checks_preserve_all_source_bytes',
    'uncommitted_marker_scratch_never_resets_a_retained_sequence',
    'maintenance_deadlines_and_closed_input_bounds_precede_filesystem_mutation',
    'global_floor_pagination_keeps_the_original_frozen_horizon',
    'ordinary_append_intent_must_recover_before_a_pending_attempt_can_be_sealed',
    'corrupt_active_header_during_transition_preserves_the_verified_archive',
    'unjoined_worker_keeps_exclusive_ownership_and_prepaid_attempt_capacity',
]


def replace(name, before, after):
    path = Path(name)
    text = path.read_text()
    if after in text:
        return
    if text.count(before) != 1:
        raise SystemExit('candidate-context-mismatch:' + name + ':' + before[:70])
    path.write_text(text.replace(before, after))


def prepare():
    replace(STORE, 'mod io;\nmod query;', 'mod io;\npub(super) mod lifecycle;\nmod query;')
    replace(STORE, '#[derive(Serialize, Deserialize)]\n#[serde(rename_all = "camelCase", deny_unknown_fields)]\nstruct Mode {',
            '#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]\n#[serde(rename_all = "camelCase", deny_unknown_fields)]\nstruct Mode {')
    replace(STORE, '    sessions: u64,\n}', '    sessions: u64,\n    #[serde(default, skip_serializing_if = "Option::is_none", deserialize_with = "codec::present")]\n    lineage: Option<lifecycle::EpochLink>,\n}')
    replace(STORE, '    head: Head,\n    entries: Vec<Entry>,', '    head: Head,\n    first_sequence: u64,\n    seed_digest: String,\n    entries: Vec<Entry>,')
    replace(STORE, '        let root = io::root(path)?;\n        let allowed = [', '        let root = io::root(path)?;\n        lifecycle::guard_open(&root)?;\n        let allowed = [')
    replace(STORE, '            "record.next",\n            "records",', '            "record.next",\n            "ROLLOVER.next",\n            "TRANSFER.next",\n            "records",')
    replace(STORE, 'let names = io::names(&root.path, 10)?;', 'let names = io::names(&root.path, 12)?;')
    replace(STORE, '                sessions: 0,\n', '                sessions: 0,\n                lineage: None,\n')
    replace(STORE, '''        if mode.format_version != 1
            || mode.retention != "reject-new"
            || !codec::hex(&mode.epoch, 32)
        {
            return Err(corrupt());
        }''', '        let (first_sequence, seed_digest, unknown) = lifecycle::epoch_state(&mode)?;')
    replace(STORE, '            root,\n            head,\n            entries:', '            root,\n            head,\n            first_sequence,\n            seed_digest,\n            entries:')
    replace(STORE, '            unknown: 0,\n', '            unknown,\n')
    replace(STORE, 'previous_session_loss_unknown: mode.sessions > 0,', 'previous_session_loss_unknown: mode.sessions > 0 || mode.lineage.is_some(),')
    replace(STORE, '        store.scan()?;\n        mode.initialized', '        store.scan()?;\n        io::remove(&store.root.path.join("ROLLOVER.next"), 16384)?;\n        io::remove(&store.root.path.join("TRANSFER.next"), 16384)?;\n        mode.initialized')
    replace(STORE, '    fn scan(&mut self) -> Result<()> {\n        let names', '    fn scan(&mut self) -> Result<()> {\n        self.scan_with_deadline(None)\n    }\n    fn scan_with_deadline(&mut self, deadline: Option<std::time::Instant>) -> Result<()> {\n        check_scan_deadline(deadline)?;\n        let names')
    replace(STORE, 'self.head.next_sequence != names.len() as u64 + 1', 'self.first_sequence.checked_add(names.len() as u64) != Some(self.head.next_sequence)')
    replace(STORE, 'let mut previous = "0".repeat(64);', 'let mut previous = self.seed_digest.clone();')
    replace(STORE, '        for (i, name) in names.iter().enumerate() {\n            if name != &filename(i as u64 + 1) {', '        for (i, name) in names.iter().enumerate() {\n            check_scan_deadline(deadline)?;\n            let sequence = self.first_sequence.checked_add(i as u64).ok_or_else(corrupt)?;\n            if name != &filename(sequence) {')
    replace(STORE, 'record.sequence != i as u64 + 1', 'record.sequence != sequence')
    replace(STORE, '        if total != self.head.bytes || previous != self.head.last_digest {', '        check_scan_deadline(deadline)?;\n        if total != self.head.bytes || previous != self.head.last_digest {')
    replace(STORE, 'fn filename(sequence: u64) -> String {', '''fn check_scan_deadline(deadline: Option<std::time::Instant>) -> Result<()> {
    if deadline.is_some_and(|value| std::time::Instant::now() >= value) {
        return Err(super::error(latent_core::PlatformErrorCode::DeadlineExceeded, "audit-maintenance-deadline"));
    }
    Ok(())
}
fn filename(sequence: u64) -> String {''')
    replace(STORE, '.and_then(|bytes| bytes.checked_add(2 * 64))', '.and_then(|bytes| bytes.checked_add(4 * 64))')
    query = STORE[:-3] + '/query.rs'
    replace(query, 'if a > h || h >= self.head.next_sequence {', 'if a < self.first_sequence - 1 || a > h || h >= self.head.next_sequence {')
    replace(query, '(0, self.head.next_sequence - 1)', '(self.first_sequence - 1, self.head.next_sequence - 1)')
    replace(query, '.skip(usize::try_from(after).map_err(|_| corrupt())?)', '.skip(usize::try_from(after - (self.first_sequence - 1)).map_err(|_| corrupt())?)')
    replace(query, 'retained_floor: 1,', 'retained_floor: self.first_sequence,')
    io = STORE[:-3] + '/io.rs'
    replace(io, '        Some("INTENT" | "INTENT.next" | "record.next") => Ok(16384),', '''        Some("CUSTODY" | "CUSTODY.next" | "SEAL" | "SEAL.next") => Ok(4096),
        Some("ROLLOVER" | "ROLLOVER.next" | "TRANSFER" | "TRANSFER.next") => Ok(16384),
        Some("INTENT" | "INTENT.next" | "record.next") => Ok(16384),''')
    replace('crates/latent-audit/src/durable.rs', 'pub use model::*;', 'pub use model::*;\npub use store::lifecycle::{AuditMaintenance, AuditArchiveCoverage, AuditArchivePage, AuditRolloverReceipt, AuditTransferReceipt};')
    replace(ROOT + '.rs', '#[cfg(all(test, unix))]', '#[cfg(all(test, target_os = "linux"))]')
    replace(ROOT + '.rs', '    pub fn transfer(\n', '    #[expect(clippy::too_many_arguments, reason = "Stopped-owner transfer requires exact original archive, destination and operation selectors")]\n    pub fn transfer(\n')
    replace(ROOT + '.rs', '    fn new(timeout: Duration) -> Result<Self> {\n', '''    fn new(timeout: Duration) -> Result<Self> {
        if !cfg!(target_os = "linux") {
            return Err(failure(PlatformErrorCode::IncompatibleContract, "audit-maintenance-platform-unsupported"));
        }
''')
    model = ROOT + '/model.rs'
    replace(model, '    pub transferred_through: u64,\n}\n', '    pub transferred_through: u64,\n    pub destination_digest: String,\n}\n')
    replace(model, '            Some(receipt) if codec::hex(&receipt.operation_id, 32) && codec::hex(&receipt.epoch, 32)', '            Some(receipt) if codec::hex(&receipt.operation_id, 32) && codec::hex(&receipt.epoch, 32)\n                && codec::hex(&receipt.destination_digest, 64)')
    storage = ROOT + '/storage.rs'
    replace(storage, '    inventory(root, value, false)?;\n    let mut previous', '    inventory(root, value, false)?;\n    verify_retained(root, value, deadline)\n}\n\npub(super) fn verify_retained(root: &io::Root, value: &Custody, deadline: Deadline) -> Result<()> {\n    let mut previous')
    replace(storage, '        if !source.entries.iter().any(|entry| filename(entry.sequence) == name)\n            || io::read(&records.join(&name), 16384)? != io::read(&original, 16384)?', '        record_index(source, &name)?;\n        if io::read(&records.join(&name), 16384)? != io::read(&original, 16384)?')
    replace(storage, '        if !verified.entries.iter().any(|entry| filename(entry.sequence) == *name)\n            || io::read(&source.join("records").join(name), 16384)?', '        record_index(verified, name)?;\n        if io::read(&source.join("records").join(name), 16384)?')
    replace(storage, '            io::sync(&records)?;\n', '            io::sync(&records)?;\n            super::cut(11)?;\n')
    replace(storage, '    let (verified, actual) = archive_locked(root, deadline)?;', '    super::cut(12)?;\n    let (verified, actual) = archive_locked(root, deadline)?;')
    path = Path(storage)
    text = path.read_text()
    if 'fn record_index(' not in text:
        text += '''
fn record_index(store: &Store, name: &str) -> Result<usize> {
    let raw = name.strip_prefix("r-").filter(|value| codec::hex(value, 16)).ok_or_else(corrupt)?;
    let sequence = u64::from_str_radix(raw, 16).map_err(|_| corrupt())?;
    let offset = sequence.checked_sub(store.first_sequence).ok_or_else(corrupt)?;
    let index = usize::try_from(offset).map_err(|_| corrupt())?;
    if store.entries.get(index).is_none_or(|entry| entry.sequence != sequence) || filename(sequence) != name {
        return Err(corrupt());
    }
    Ok(index)
}
'''
        path.write_text(text)
    replace(ROOT + '/rollover.rs', 'let transition = prepare(&source, mode, old_custody, &archive_root)?;', 'let transition = prepare(&source, mode, old_custody, &archive_root)?.identify(operation)?;')
    replace(ROOT + '/transfer.rs', 'storage, Deadline, Mode, Result, Store', 'storage, Deadline, Result, Store')
    path = Path('tools/ci/suites.json')
    data = json.loads(path.read_text())
    rows = [row for row in data['suites'] if row.get('package') == 'latent-audit' and row.get('kind') == 'lib']
    if len(rows) != 1:
        raise SystemExit('ambiguous-audit-suite-owner')
    row = rows[0]
    cases = {'durable::store::lifecycle::tests::' + name for name in CASES}
    added = cases - set(row['expectedCases'])
    row['expectedCases'] = sorted(set(row['expectedCases']) | cases)
    row['minimumCases'] += len(added)
    path.write_text(json.dumps(data, indent=2) + '\n')
    subprocess.run(['rustup', 'run', '1.97.1', 'rustfmt', '--edition', '2021', '--config', 'skip_children=true', *RUST], check=True)


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
