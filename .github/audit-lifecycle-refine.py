"""Exact-source qualification corrections; no remote writes or branch updates."""
import runpy
import subprocess
from pathlib import Path

candidate = runpy.run_path('.github/audit-lifecycle-candidate.py')
candidate['prepare']()
replace = candidate['replace']
name = 'crates/latent-audit/src/durable/store/lifecycle/tests.rs'
text = Path(name).read_text()
start = text.index('#[test]\nfn unjoined_worker_keeps_exclusive_ownership_and_prepaid_attempt_capacity()')
assert text[start:].count('#[test]') == 1
Path(name).write_text(text[:start] + '''#[test]
fn unjoined_worker_keeps_exclusive_ownership_and_prepaid_attempt_capacity() {
    let fixture = Fixture::new();
    let (handle, mut worker) = DirectoryPhase2AuditJournal::open(&fixture.root, small()).unwrap();
    let epoch = fixture.epoch();
    let mut pending = handle.reserve_control_critical(&attempt()).unwrap()
        .begin().blocking_wait().unwrap();
    pending.mutation_started().unwrap();
    handle.close();
    assert!(!worker.join_until(Instant::now() + Duration::from_millis(10)).unwrap());
    let error = AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    // Closure cannot refund a started attempt or discard its prepaid terminal.
    let acknowledgement = pending.finish(conclusion()).blocking_wait().unwrap();
    assert_eq!(acknowledgement.sequence, 2);
    assert!(worker.join_until(Instant::now() + TIMEOUT).unwrap());
    drop(handle);
    fixture.roll(1);
}
''')
subprocess.run(['rustup', 'run', '1.97.1', 'rustfmt', '--edition', '2021', '--config', 'skip_children=true', name], check=True)
