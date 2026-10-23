use super::*;
use crate::durable::{AuditOperationResult, AuditQueryRequest, AuditReason, AuditRecordData, AuditScope, DirectoryPhase2AuditJournal};
use crate::durable::tests::{attempt, conclusion, Directory};
use latent_core::{PlatformErrorCode, TenantId};
use std::{collections::BTreeMap, fs, io::Write, os::unix::fs::{OpenOptionsExt, PermissionsExt}, path::PathBuf};

const TIMEOUT: Duration = Duration::from_secs(10);
struct Fixture { _directory: Directory, root: PathBuf, custody: PathBuf }
impl Fixture {
    fn new() -> Self {
        let directory = Directory::new();
        Self { root: directory.0.join("active"), custody: directory.0.join("archives"), _directory: directory }
    }
    fn fill(&self, unknown: bool) -> String {
        let mut store = Store::open(&self.root, small()).unwrap();
        pair(&mut store, unknown);
        store.head.epoch.clone()
    }
    fn epoch(&self) -> String { storage::canonical::<Mode>(&self.root.join("MODE"), 1024).unwrap().epoch }
    fn destination(&self) -> PathBuf { self._directory.0.join("operator-custody") }
    fn roll(&self, operation: u64) -> AuditRolloverReceipt {
        AuditMaintenance::rollover(&self.root, &self.custody, &self.epoch(), &format!("{operation:032x}"), TIMEOUT).unwrap()
    }
}
fn small() -> AuditLimits { AuditLimits { maximum_records: 2, ..AuditLimits::default() } }
fn pair(store: &mut Store, unknown: bool) {
    let a = attempt();
    let sequence = store.append(a.scope.clone(), a.actor.clone(), AuditRecordData::Attempt(a.clone())).unwrap().sequence;
    let mut c = conclusion();
    if unknown { c.result = AuditOperationResult::Unknown; c.reason = AuditReason::MutationUncertain; c.receipt_digest = None; }
    store.append(a.scope, a.actor, AuditRecordData::Outcome { attempt_sequence: sequence, conclusion: c }).unwrap();
}
fn query() -> AuditQueryRequest {
    AuditQueryRequest { scope: AuditScope::Tenant(TenantId("test".into())), filter: Default::default(),
        cursor: None, limit: 1, maximum_bytes: 32768 }
}
fn history(root: &Path) -> BTreeMap<String, Vec<u8>> {
    let mut result = BTreeMap::new();
    if !root.exists() { return result; }
    for entry in fs::read_dir(root).unwrap() {
        let entry = entry.unwrap();
        let name = entry.file_name().into_string().unwrap();
        if entry.file_type().unwrap().is_dir() {
            for (child, bytes) in history(&entry.path()) { result.insert(format!("{name}/{child}"), bytes); }
        } else { result.insert(name, fs::read(entry.path()).unwrap()); }
    }
    result
}
fn acknowledged(root: &Path) -> BTreeMap<String, Vec<u8>> {
    history(root).into_iter().filter(|(name, _)| name == "MODE" || name == "HEAD" || name.starts_with("records/")).collect()
}
fn write_private(path: &Path, bytes: &[u8]) {
    if path.exists() { fs::write(path, bytes).unwrap(); }
    else { let mut file = fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(path).unwrap(); file.write_all(bytes).unwrap(); file.sync_all().unwrap(); }
}

#[test]
fn full_epoch_rollover_preserves_bytes_and_global_sequence() {
    let fixture = Fixture::new();
    let epoch = fixture.fill(false);
    let source = Store::open(&fixture.root, small()).unwrap();
    let (_, _, cursor) = source.query(&query(), Instant::now() + TIMEOUT, 0).unwrap();
    let old_head = source.head.last_digest.clone();
    drop(source);
    let bytes = acknowledged(&fixture.root);
    let receipt = fixture.roll(1);
    assert_eq!(receipt.previous_epoch, epoch);
    assert_eq!(receipt.next_sequence, 3);
    assert_ne!(receipt.epoch, epoch);
    let archive = fixture.custody.join(&epoch);
    assert_eq!(acknowledged(&archive), bytes);
    let verified = AuditMaintenance::verify_archive(&archive, &epoch, TIMEOUT).unwrap();
    assert_eq!((verified.first_sequence, verified.high_watermark, verified.records), (1, 2, 2));
    assert!(verified.previous_session_loss_unknown);
    let mut active = Store::open(&fixture.root, small()).unwrap();
    let (_, coverage, _) = active.query(&query(), Instant::now() + TIMEOUT, 0).unwrap();
    assert_eq!((coverage.retained_floor, coverage.high_watermark), (3, 2));
    let mut old_page = query(); old_page.cursor = cursor;
    assert!(active.query(&old_page, Instant::now() + TIMEOUT, 0).is_err());
    pair(&mut active, false);
    let (records, _, _) = active.query(&query(), Instant::now() + TIMEOUT, 0).unwrap();
    assert_eq!(records[0].sequence, 3);
    assert_eq!(records[0].previous_digest, old_head);
    drop(active);
    let page = AuditMaintenance::query_archive(&archive, &epoch, &old_page, TIMEOUT).unwrap();
    assert_eq!(page.records.len(), 1);
    assert_eq!(page.records[0].sequence, 2);
    assert!(page.next_cursor.is_none());
    old_page.scope = AuditScope::Tenant(TenantId("another".into()));
    assert!(AuditMaintenance::query_archive(&archive, &epoch, &old_page, TIMEOUT).is_err());
}

#[test]
fn rollover_cutpoints_resume_original_identity_without_reset() {
    for point in [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12] {
        let fixture = Fixture::new();
        let epoch = fixture.fill(false);
        let bytes = acknowledged(&fixture.root);
        FAIL.with(|value| value.set(point));
        assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"1".repeat(32), TIMEOUT).is_err(), "cut {point}");
        assert_eq!(FAIL.with(std::cell::Cell::get), 0, "cut was not reached: {point}");
        if fixture.root.join("ROLLOVER").exists() {
            assert!(Store::open(&fixture.root, small()).is_err(), "maintenance marker must block a writer");
        }
        assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"2".repeat(32), TIMEOUT).is_err());
        let result = AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"1".repeat(32), TIMEOUT).unwrap();
        assert_eq!(result.next_sequence, 3);
        assert_eq!(acknowledged(&fixture.custody.join(&epoch)), bytes);
        let replay = AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"1".repeat(32), TIMEOUT).unwrap();
        assert!(replay.already_completed);
        assert_eq!(replay.epoch, result.epoch);
        assert!(!fixture.root.join("ROLLOVER").exists());
        assert_eq!(Store::open(&fixture.root, small()).unwrap().head.next_sequence, 3);
    }
}

#[test]
fn pending_attempts_and_live_owners_block_maintenance_and_unknown_stays_unknown() {
    let fixture = Fixture::new();
    let mut store = Store::open(&fixture.root, small()).unwrap();
    let epoch = store.head.epoch.clone();
    let a = attempt();
    let sequence = store.append(a.scope.clone(), a.actor.clone(), AuditRecordData::Attempt(a.clone())).unwrap().sequence;
    assert_eq!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).unwrap_err().code, PlatformErrorCode::Unavailable);
    drop(store);
    let before = acknowledged(&fixture.root);
    let error = AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).unwrap_err();
    assert_eq!(error.message, "audit-critical-pending");
    assert_eq!(acknowledged(&fixture.root), before);
    assert!(!fixture.custody.exists());
    let mut store = Store::open(&fixture.root, small()).unwrap();
    let mut c = conclusion(); c.result = AuditOperationResult::Unknown; c.reason = AuditReason::MutationUncertain; c.receipt_digest = None;
    store.append(a.scope, a.actor, AuditRecordData::Outcome { attempt_sequence: sequence, conclusion: c }).unwrap();
    drop(store);
    fixture.roll(1);
    let active = Store::open(&fixture.root, small()).unwrap();
    assert_eq!(active.unknown, 1);
    assert_eq!(active.head.next_sequence, 3);
    drop(active);
    let mut q = query(); q.limit = 128;
    let page = AuditMaintenance::query_archive(&fixture.custody.join(&epoch), &epoch, &q, TIMEOUT).unwrap();
    assert_eq!(page.coverage.unknown_outcomes, 1);
    assert!(matches!(&page.records[1].data, AuditRecordData::Outcome { conclusion, .. } if conclusion.result == AuditOperationResult::Unknown));
}

#[test]
fn full_custody_requires_verified_oldest_transfer_before_another_rollover() {
    let fixture = Fixture::new();
    let mut receipts = Vec::new();
    for operation in 1..=4 { fixture.fill(operation == 1); receipts.push(fixture.roll(operation)); }
    let epoch = fixture.fill(false);
    let before = acknowledged(&fixture.root);
    let error = AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &format!("{:032x}", 5), TIMEOUT).unwrap_err();
    assert_eq!(error.message, "audit-archive-capacity");
    assert_eq!(acknowledged(&fixture.root), before);
    assert!(!fixture.root.join("ROLLOVER").exists());
    let first = &receipts[0];
    let destination = fixture.destination();
    let archived = acknowledged(&fixture.custody.join(&first.previous_epoch));
    let transfer = AuditMaintenance::transfer(&fixture.root, &fixture.custody, &destination,
        &first.previous_epoch, &first.archive_seal, &"f".repeat(32), TIMEOUT).unwrap();
    assert_eq!(transfer.transferred_through, 2);
    assert_eq!(acknowledged(&destination), archived);
    assert!(!fixture.custody.join(&first.previous_epoch).exists());
    AuditMaintenance::verify_archive(&destination, &first.previous_epoch, TIMEOUT).unwrap();
    let result = fixture.roll(5);
    assert_eq!(result.next_sequence, 11);
    let active = Store::open(&fixture.root, small()).unwrap();
    assert_eq!(active.unknown, 1);
    assert_eq!(active.first_sequence, 11);
    let root = storage::existing_root(&fixture.custody).unwrap();
    let index = storage::read_custody(&root).unwrap();
    assert_eq!(index.archives.len(), 4);
    assert_eq!(index.transferred_through, 2);
}

#[test]
fn transfer_cutpoints_keep_custody_until_the_destination_is_reverified() {
    for point in 20..=26 {
        let fixture = Fixture::new();
        let epoch = fixture.fill(false);
        let rolled = fixture.roll(1);
        let destination = fixture.destination();
        let original = acknowledged(&fixture.custody.join(&epoch));
        FAIL.with(|value| value.set(point));
        assert!(AuditMaintenance::transfer(&fixture.root, &fixture.custody, &destination, &epoch,
            &rolled.archive_seal, &"e".repeat(32), TIMEOUT).is_err(), "cut {point}");
        assert_eq!(FAIL.with(std::cell::Cell::get), 0, "cut was not reached: {point}");
        if point != 26 {
            assert!(Store::open(&fixture.root, small()).is_err());
            let before = history(&fixture.custody);
            let unavailable = fixture._directory.0.join("unmounted-archive");
            fs::rename(&destination, &unavailable).unwrap();
            assert!(AuditMaintenance::transfer(&fixture.root, &fixture.custody, &destination, &epoch,
                &rolled.archive_seal, &"e".repeat(32), TIMEOUT).is_err());
            assert_eq!(history(&fixture.custody), before);
            fs::rename(&unavailable, &destination).unwrap();
        }
        let result = AuditMaintenance::transfer(&fixture.root, &fixture.custody, &destination, &epoch,
            &rolled.archive_seal, &"e".repeat(32), TIMEOUT).unwrap();
        assert_eq!(result.transferred_through, 2);
        assert_eq!(acknowledged(&destination), original);
        assert!(!fixture.custody.join(&epoch).exists());
        assert!(!fixture.root.join("TRANSFER").exists());
        let changed = fixture._directory.0.join("another-target");
        assert!(AuditMaintenance::transfer(&fixture.root, &fixture.custody, &changed, &epoch,
            &rolled.archive_seal, &"e".repeat(32), TIMEOUT).is_err());
        assert!(!changed.exists());
    }
}

#[test]
fn corrupt_and_missing_sealed_history_is_not_repaired_or_deleted() {
    for missing in [false, true] {
        let fixture = Fixture::new();
        let epoch = fixture.fill(false);
        fixture.roll(1);
        let archive = fixture.custody.join(&epoch);
        let record = archive.join("records/r-0000000000000001");
        if missing { fs::remove_file(&record).unwrap(); } else { fs::write(&record, b"corrupt").unwrap(); }
        let retained = history(&archive);
        assert!(AuditMaintenance::verify_archive(&archive, &epoch, TIMEOUT).is_err());
        fixture.fill(false);
        let active = acknowledged(&fixture.root);
        assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &fixture.epoch(), &"b".repeat(32), TIMEOUT).is_err());
        assert_eq!(acknowledged(&fixture.root), active);
        assert_eq!(history(&archive), retained);
    }
}

#[test]
fn a_sealed_staging_archive_with_missing_history_blocks_capacity_release() {
    let fixture = Fixture::new();
    let epoch = fixture.fill(false);
    let active = acknowledged(&fixture.root);
    FAIL.with(|v| v.set(12));
    assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).is_err());
    fs::remove_file(fixture.custody.join("stage/records/r-0000000000000001")).unwrap();
    assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).is_err());
    assert_eq!(acknowledged(&fixture.root), active);
    assert!(!fixture.custody.join("stage/records/r-0000000000000001").exists());
}

#[test]
fn private_path_and_archive_identity_checks_preserve_all_source_bytes() {
    let fixture = Fixture::new();
    let epoch = fixture.fill(false);
    let before = acknowledged(&fixture.root);
    assert!(AuditMaintenance::rollover(&fixture.root, &fixture.root.join("nested"), &epoch, &"a".repeat(32), TIMEOUT).is_err());
    assert!(!fixture.root.join("nested").exists());
    let target = fixture._directory.0.join("external"); fs::create_dir(&target).unwrap();
    std::os::unix::fs::symlink(&target, &fixture.custody).unwrap();
    assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).is_err());
    assert_eq!(acknowledged(&fixture.root), before);
    fs::remove_file(&fixture.custody).unwrap();
    fixture.roll(1);
    let archive = fixture.custody.join(&epoch);
    assert!(AuditMaintenance::verify_archive(&archive, &"0".repeat(32), TIMEOUT).is_err());
    fs::set_permissions(&archive, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(AuditMaintenance::verify_archive(&archive, &epoch, TIMEOUT).is_err());
    fs::set_permissions(&archive, fs::Permissions::from_mode(0o700)).unwrap();
    let alias = fixture._directory.0.join("hardlink");
    fs::hard_link(archive.join("records/r-0000000000000001"), &alias).unwrap();
    assert!(AuditMaintenance::verify_archive(&archive, &epoch, TIMEOUT).is_err());
    fs::remove_file(alias).unwrap();
    AuditMaintenance::verify_archive(&archive, &epoch, TIMEOUT).unwrap();
}

#[test]
fn uncommitted_marker_scratch_never_resets_a_retained_sequence() {
    let fixture = Fixture::new();
    fixture.fill(false);
    write_private(&fixture.root.join("ROLLOVER.next"), b"interrupted uncommitted staging");
    write_private(&fixture.root.join("TRANSFER.next"), b"interrupted uncommitted staging");
    let store = Store::open(&fixture.root, small()).unwrap();
    assert_eq!(store.head.next_sequence, 3);
    assert_eq!(store.head.records, 2);
    assert!(!fixture.root.join("ROLLOVER.next").exists());
    assert!(!fixture.root.join("TRANSFER.next").exists());
}

#[test]
fn maintenance_deadlines_and_closed_input_bounds_precede_filesystem_mutation() {
    let fixture = Fixture::new();
    let epoch = fixture.fill(false);
    let before = history(&fixture.root);
    for duration in [Duration::ZERO, Duration::from_secs(121)] {
        assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), duration).is_err());
    }
    assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, "not-an-identity", TIMEOUT).is_err());
    assert!(rollover::run(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), Deadline(Instant::now() - TIMEOUT)).is_err());
    assert_eq!(history(&fixture.root), before);
    assert!(!fixture.custody.exists());
}

#[test]
fn global_floor_pagination_keeps_the_original_frozen_horizon() {
    let fixture = Fixture::new();
    fixture.fill(false); fixture.roll(1);
    fixture.fill(false); fixture.roll(2);
    let mut store = Store::open(&fixture.root, AuditLimits { maximum_records: 4, ..AuditLimits::default() }).unwrap();
    pair(&mut store, true);
    let (first, coverage, next) = store.query(&query(), Instant::now() + TIMEOUT, 0).unwrap();
    assert_eq!((first[0].sequence, coverage.retained_floor, coverage.high_watermark), (5, 5, 6));
    pair(&mut store, false);
    let mut request = query(); request.cursor = next;
    let (last, coverage, next) = store.query(&request, Instant::now() + TIMEOUT, 0).unwrap();
    assert_eq!((last[0].sequence, coverage.high_watermark), (6, 6));
    assert!(next.is_none());
    assert_eq!(coverage.unknown_outcomes, 1);
}

#[test]
fn ordinary_append_intent_must_recover_before_a_pending_attempt_can_be_sealed() {
    let fixture = Fixture::new();
    let mut store = Store::open(&fixture.root, small()).unwrap();
    let epoch = store.head.epoch.clone();
    let a = attempt();
    super::super::FAIL.with(|v| v.set(3));
    assert!(store.append(a.scope.clone(), a.actor.clone(), AuditRecordData::Attempt(a.clone())).is_err());
    drop(store);
    assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).is_err());
    assert!(!fixture.custody.exists());
    let mut store = Store::open(&fixture.root, small()).unwrap();
    assert_eq!(store.pending.as_ref().unwrap().sequence, 1);
    let mut c = conclusion(); c.result = AuditOperationResult::Unknown; c.reason = AuditReason::MutationUncertain; c.receipt_digest = None;
    store.append(a.scope, a.actor, AuditRecordData::Outcome { attempt_sequence: 1, conclusion: c }).unwrap();
    drop(store);
    fixture.roll(1);
    assert_eq!(AuditMaintenance::verify_archive(&fixture.custody.join(&epoch), &epoch, TIMEOUT).unwrap().unknown_outcomes, 1);
}

#[test]
fn corrupt_active_header_during_transition_preserves_the_verified_archive() {
    let fixture = Fixture::new();
    let epoch = fixture.fill(false);
    let before = acknowledged(&fixture.root);
    FAIL.with(|v| v.set(4));
    assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).is_err());
    write_private(&fixture.root.join("HEAD"), b"{}\n");
    let corrupt_source = acknowledged(&fixture.root);
    assert!(AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).is_err());
    assert_eq!(acknowledged(&fixture.root), corrupt_source);
    assert_eq!(acknowledged(&fixture.custody.join(&epoch)), before);
    write_private(&fixture.root.join("HEAD"), &before["HEAD"]);
    AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).unwrap();
}

#[test]
fn unjoined_worker_keeps_exclusive_ownership_and_prepaid_attempt_capacity() {
    let fixture = Fixture::new();
    let (handle, mut worker) = DirectoryPhase2AuditJournal::open(&fixture.root, small()).unwrap();
    let epoch = fixture.epoch();
    let reservation = handle.reserve_control_critical(&attempt()).unwrap();
    handle.close();
    assert!(!worker.join_until(Instant::now() + Duration::from_millis(10)).unwrap());
    let error = AuditMaintenance::rollover(&fixture.root, &fixture.custody, &epoch, &"a".repeat(32), TIMEOUT).unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    drop(reservation);
    assert!(worker.join_until(Instant::now() + TIMEOUT).unwrap());
    drop(handle);
    fixture.fill(false);
    fixture.roll(1);
}
