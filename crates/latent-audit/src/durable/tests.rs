use super::*;
use latent_core::{ArtifactBlobDigest, TenantId};
use std::{
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant},
};
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "lsf-audit-{}-{}-{}",
            std::process::id(),
            store::now(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        // Keep failure evidence and never mask an assertion with a second
        // destructor panic. TestWorker joins before normal directory cleanup.
        if !std::thread::panicking() {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }
}
struct TestWorker {
    worker: AuditWorker,
    handle: AuditHandle,
}
impl std::ops::Deref for TestWorker {
    type Target = AuditWorker;
    fn deref(&self) -> &AuditWorker {
        &self.worker
    }
}
impl std::ops::DerefMut for TestWorker {
    fn deref_mut(&mut self) -> &mut AuditWorker {
        &mut self.worker
    }
}
impl Drop for TestWorker {
    fn drop(&mut self) {
        self.handle.close();
        let result = self
            .worker
            .join_until(Instant::now() + Duration::from_secs(5));
        if !std::thread::panicking() {
            assert!(
                matches!(result, Ok(true)),
                "test worker did not actually stop"
            );
        }
    }
}
fn open(
    path: impl AsRef<std::path::Path>,
    limits: AuditLimits,
) -> Result<(AuditHandle, TestWorker)> {
    DirectoryPhase2AuditJournal::open(path, limits).map(|(handle, worker)| {
        let guard = TestWorker {
            worker,
            handle: handle.clone(),
        };
        (handle, guard)
    })
}
fn digest() -> ArtifactBlobDigest {
    format!("sha256:{}", "a".repeat(64)).parse().unwrap()
}
fn attempt() -> AuditOperationAttempt {
    AuditOperationAttempt {
        scope: AuditScope::Tenant(TenantId("test".into())),
        actor: AuditActorIdentity {
            kind: AuditActorKind::Host,
            subject: "operator".into(),
        },
        operation_id: "one".into(),
        request_digest: digest(),
        preview_receipt_digest: Some(digest()),
        action: AuditControlAction::Publish,
        identities: AuditIdentities::default(),
        replay: false,
        expected_generation: Some(0),
        expected_deployment_generation: None,
        expected_rollout_revision: None,
        occurred_at_unix_millis: 1,
    }
}
fn conclusion() -> AuditOperationConclusion {
    AuditOperationConclusion {
        result: AuditOperationResult::Committed,
        reason: AuditReason::Committed,
        receipt_digest: Some(digest()),
        identities: AuditIdentities::default(),
        replay: false,
        occurred_at_unix_millis: 2,
    }
}

#[test]
fn expected_rollout_revision_is_distinct_from_other_generations() {
    let mut value = attempt();
    value.expected_rollout_revision = Some(0);
    assert!(codec::attempt(&value).is_err());
    value.action = AuditControlAction::Rollout;
    assert!(codec::attempt(&value).is_err());
    value.identities.rollout = Some("rollout".into());
    value.expected_generation = None;
    codec::attempt(&value).unwrap();
    let bytes = codec::encode(&value, 4096).unwrap();
    let decoded: AuditOperationAttempt = codec::decode(&bytes, 4096).unwrap();
    assert_eq!(decoded, value);
    let mut json = serde_json::to_value(value).unwrap();
    json["expectedRolloutRevision"] = serde_json::Value::Null;
    assert!(serde_json::from_value::<AuditOperationAttempt>(json).is_err());
}
fn query(scope: AuditScope) -> AuditQueryRequest {
    AuditQueryRequest {
        scope,
        filter: AuditFilter::default(),
        cursor: None,
        limit: 128,
        maximum_bytes: 65536,
    }
}
fn stop(handle: &AuditHandle, worker: &mut AuditWorker) {
    handle.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
#[test]
fn invalid_limits_reject_without_root_creation() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let limits = AuditLimits {
        maximum_records: usize::MAX,
        ..AuditLimits::default()
    };
    assert!(open(&path, limits).is_err());
    assert!(!path.exists());
}

#[cfg(unix)]
#[test]
fn durable_attempt_outcome_reopen_and_page_lease() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let mut candidate = handle
        .try_reserve_critical(&attempt())
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    assert_eq!(candidate.sequence(), 1);
    assert_eq!(handle.snapshot().reserved_records, 1);
    candidate.mutation_started().unwrap();
    assert_eq!(
        candidate
            .finish(conclusion())
            .blocking_wait()
            .unwrap()
            .sequence,
        2
    );
    let page = handle
        .query(
            query(attempt().scope),
            Instant::now() + Duration::from_secs(2),
        )
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert_eq!(page.records().len(), 2);
    let (_, _, _, lease) = page.into_parts();
    assert_eq!(handle.snapshot().query_owners, 1);
    let lease2 = lease.clone();
    drop(lease);
    assert_eq!(handle.snapshot().query_owners, 1);
    stop(&handle, &mut worker);
    let (reopened_handle, mut reopened_worker) = open(&path, AuditLimits::default()).unwrap();
    assert_eq!(reopened_handle.snapshot().retained_records, 2);
    drop(lease2);
    assert_eq!(handle.snapshot().query_owners, 0);
    stop(&reopened_handle, &mut reopened_worker);
}
#[cfg(unix)]
#[test]
fn abandoned_before_and_after_start_have_distinct_durable_outcomes() {
    for started in [false, true] {
        let directory = Directory::new();
        let (handle, mut worker) = open(directory.0.join("audit"), AuditLimits::default()).unwrap();
        let mut candidate = handle
            .try_reserve_critical(&attempt())
            .unwrap()
            .begin()
            .blocking_wait()
            .unwrap();
        if started {
            candidate.mutation_started().unwrap();
        }
        drop(candidate);
        stop(&handle, &mut worker);
        let (reopened, mut reopened_worker) =
            open(directory.0.join("audit"), AuditLimits::default()).unwrap();
        let page = reopened
            .query(
                query(attempt().scope),
                Instant::now() + Duration::from_secs(2),
            )
            .unwrap()
            .blocking_wait()
            .unwrap();
        assert_eq!(page.records().len(), 2);
        let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
            panic!("outcome")
        };
        assert_eq!(
            conclusion.result,
            if started {
                AuditOperationResult::Unknown
            } else {
                AuditOperationResult::NotStarted
            }
        );
        assert_eq!(reopened.snapshot().unknown_outcomes, u64::from(started));
        stop(&reopened, &mut reopened_worker);
    }
}
#[cfg(unix)]
#[test]
fn all_transaction_cutpoints_recover_without_sequence_reuse() {
    for point in 1..=4 {
        let directory = Directory::new();
        let path = directory.0.join("audit");
        let mut journal = store::Store::open(&path, AuditLimits::default()).unwrap();
        store::FAIL.with(|f| f.set(point));
        let candidate = attempt();
        assert!(journal
            .append(
                candidate.scope.clone(),
                candidate.actor.clone(),
                AuditRecordData::Attempt(candidate)
            )
            .is_err());
        drop(journal);
        let recovered = store::Store::open(&path, AuditLimits::default()).unwrap();
        assert_eq!(recovered.summary().0, usize::from(point >= 2));
        assert_eq!(recovered.summary().2, if point >= 2 { 2 } else { 1 });
    }
}
#[cfg(unix)]
#[test]
fn acknowledged_record_missing_is_corruption_not_a_new_epoch() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let candidate = handle
        .try_reserve_critical(&attempt())
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    candidate.finish(conclusion()).blocking_wait().unwrap();
    stop(&handle, &mut worker);
    std::fs::remove_file(path.join("records/r-0000000000000002")).unwrap();
    assert!(open(&path, AuditLimits::default()).is_err());
}
#[test]
fn strict_model_rejects_unknown_null_and_invalid_component() {
    let mut candidate = attempt();
    candidate.identities.component = Some(latent_core::ReleaseDigest("sha256:component".into()));
    assert!(codec::attempt(&candidate).is_err());
    let bytes = codec::encode(&attempt(), 16384).unwrap();
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    value["expectedGeneration"] = serde_json::Value::Null;
    assert!(
        codec::decode::<AuditOperationAttempt>(&serde_json::to_vec(&value).unwrap(), 16384)
            .is_err()
    );
    value["expectedGeneration"] = 0.into();
    value["credential"] = "secret".into();
    assert!(
        codec::decode::<AuditOperationAttempt>(&serde_json::to_vec(&value).unwrap(), 16384)
            .is_err()
    );
}

#[cfg(unix)]
#[test]
fn close_retains_live_attempt_and_accepts_its_prepaid_known_outcome() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let mut candidate = handle
        .try_reserve_critical(&attempt())
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    candidate.mutation_started().unwrap();
    handle.close();
    assert!(!worker.join_until(Instant::now()).unwrap());
    assert_eq!(handle.snapshot().reserved_records, 1);
    assert_eq!(handle.snapshot().pending_attempts, 1);
    assert!(open(&path, AuditLimits::default()).is_err());
    let ack = candidate.finish(conclusion()).blocking_wait().unwrap();
    assert_eq!(ack.sequence, 2);
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
    let (reopened, mut reopened_worker) = open(&path, AuditLimits::default()).unwrap();
    assert_eq!(reopened.snapshot().unknown_outcomes, 0);
    assert_eq!(reopened.snapshot().retained_records, 2);
    stop(&reopened, &mut reopened_worker);
}

#[cfg(unix)]
#[test]
fn private_modes_ancestors_and_missing_initialized_head_fail_closed() {
    use std::os::unix::fs::{symlink, PermissionsExt};
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    assert_eq!(
        std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o700
    );
    assert_eq!(
        std::fs::metadata(path.join("MODE"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    assert!(!handle.snapshot().previous_session_loss_unknown);
    stop(&handle, &mut worker);
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    assert!(handle.snapshot().previous_session_loss_unknown);
    stop(&handle, &mut worker);
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
    assert!(open(&path, AuditLimits::default()).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let link = directory.0.join("alias");
    symlink(&path, &link).unwrap();
    assert!(open(&link, AuditLimits::default()).is_err());
    std::fs::remove_file(path.join("HEAD")).unwrap();
    assert!(open(&path, AuditLimits::default()).is_err());
}

#[cfg(unix)]
#[test]
fn partial_unreferenced_stage_recovers_but_unknown_and_links_are_preserved() {
    use std::io::Write;
    use std::os::unix::fs::{symlink, OpenOptionsExt};
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    stop(&handle, &mut worker);
    let stage = path.join("record.next");
    std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&stage)
        .unwrap()
        .write_all(b"{partial")
        .unwrap();
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    assert!(!stage.exists());
    stop(&handle, &mut worker);
    symlink("absent", &stage).unwrap();
    assert!(open(&path, AuditLimits::default()).is_err());
    assert!(std::fs::symlink_metadata(&stage)
        .unwrap()
        .file_type()
        .is_symlink());
    std::fs::remove_file(stage).unwrap();
    let unknown = path.join("operator-note");
    std::fs::write(&unknown, b"keep").unwrap();
    assert!(open(&path, AuditLimits::default()).is_err());
    assert_eq!(std::fs::read(unknown).unwrap(), b"keep");
}

#[cfg(unix)]
#[test]
fn recovered_pending_reserves_terminal_and_unknown_is_durable() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let mut store = store::Store::open(&path, AuditLimits::default()).unwrap();
    let candidate = attempt();
    store
        .append(
            candidate.scope.clone(),
            candidate.actor.clone(),
            AuditRecordData::Attempt(candidate),
        )
        .unwrap();
    drop(store);
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    assert_eq!(handle.snapshot().reserved_records, 1);
    let pending = handle.pending_attempts().unwrap();
    assert_eq!(pending.len(), 1);
    assert!(handle.try_reserve_critical(&attempt()).is_err());
    let mut terminal = conclusion();
    terminal.result = AuditOperationResult::Unknown;
    terminal.reason = AuditReason::ReceiptUnavailable;
    terminal.receipt_digest = None;
    handle
        .reconcile(pending[0].sequence, terminal)
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert_eq!(handle.snapshot().unknown_outcomes, 1);
    assert_eq!(handle.snapshot().reserved_records, 0);
    stop(&handle, &mut worker);
}

#[cfg(unix)]
#[test]
fn query_scope_scan_and_frozen_cursor_are_independent_of_future_appends() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let limits = AuditLimits {
        maximum_scan_entries: 1,
        ..Default::default()
    };
    let mut store = store::Store::open(&path, limits).unwrap();
    for scope in [
        AuditScope::Node,
        attempt().scope.clone(),
        attempt().scope.clone(),
    ] {
        let event = observation(scope);
        store
            .append(
                event.scope.clone(),
                event.actor.clone(),
                AuditRecordData::Observation(event),
            )
            .unwrap();
    }
    drop(store);
    let (handle, mut worker) = open(&path, limits).unwrap();
    let page = handle
        .query(
            query(attempt().scope),
            Instant::now() + Duration::from_secs(2),
        )
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert!(page.records().is_empty());
    assert_eq!(page.coverage().stop, AuditPageStop::ScanLimit);
    assert_eq!(page.coverage().high_watermark, 3);
    let cursor = page.next_cursor().unwrap().clone();
    drop(page);
    let mut forged = query(AuditScope::Node);
    forged.cursor = Some(cursor.clone());
    assert!(handle
        .query(forged, Instant::now() + Duration::from_secs(2))
        .unwrap()
        .blocking_wait()
        .is_err());
    let mut next = query(attempt().scope);
    next.cursor = Some(cursor);
    let page = handle
        .query(next, Instant::now() + Duration::from_secs(2))
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert_eq!(page.records().len(), 1);
    assert_eq!(page.records()[0].sequence, 2);
    drop(page);
    stop(&handle, &mut worker);
}
#[cfg(unix)]
fn observation(scope: AuditScope) -> AuditObservation {
    AuditObservation {
        scope,
        actor: attempt().actor,
        kind: crate::Phase2AuditEventKind::CacheMiss,
        outcome: crate::AuditOutcome::Succeeded,
        identities: AuditIdentities::default(),
        reason: AuditReason::CacheMiss,
        cache_kind: Some(AuditCacheKind::Raw),
        occurred_at_unix_millis: 1,
    }
}

#[cfg(unix)]
#[test]
fn per_append_bytes_do_not_rewrite_history_and_future_records_stay_outside_cursor() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let mut journal = store::Store::open(&path, AuditLimits::default()).unwrap();
    let mut sizes = Vec::new();
    for _ in 0..8 {
        let before = store::written_bytes();
        let event = observation(AuditScope::Node);
        journal
            .append(
                event.scope.clone(),
                event.actor.clone(),
                AuditRecordData::Observation(event),
            )
            .unwrap();
        sizes.push(store::written_bytes() - before);
    }
    assert!(sizes.iter().all(|n| *n <= sizes[0] + 128));
    let mut request = query(AuditScope::Node);
    request.limit = 1;
    let (_, coverage, next) = journal
        .query(&request, Instant::now() + Duration::from_secs(2), 0)
        .unwrap();
    assert_eq!(coverage.high_watermark, 8);
    let event = observation(AuditScope::Node);
    journal
        .append(
            event.scope.clone(),
            event.actor.clone(),
            AuditRecordData::Observation(event),
        )
        .unwrap();
    request.cursor = next;
    request.limit = 128;
    let (records, coverage, _) = journal
        .query(&request, Instant::now() + Duration::from_secs(2), 0)
        .unwrap();
    assert_eq!(records.len(), 7);
    assert_eq!(coverage.high_watermark, 8);
    assert_eq!(records.last().unwrap().sequence, 8);
}

#[cfg(unix)]
#[test]
fn deadlines_include_empty_end_cursor_and_final_read_boundary() {
    let directory = Directory::new();
    let mut journal =
        store::Store::open(&directory.0.join("audit"), AuditLimits::default()).unwrap();
    let request = query(AuditScope::Node);
    assert!(journal.query(&request, Instant::now(), 0).is_err());
    let event = observation(AuditScope::Node);
    journal
        .append(
            event.scope.clone(),
            event.actor.clone(),
            AuditRecordData::Observation(event),
        )
        .unwrap();
    store::expire_after_query_read(true);
    let result = journal.query(&request, Instant::now() + Duration::from_secs(30), 0);
    store::expire_after_query_read(false);
    assert!(matches!(result,Err(e)if e.code==latent_core::PlatformErrorCode::DeadlineExceeded));
    let filter = codec::digest(&codec::encode(&(&request.scope, &request.filter), 4096).unwrap());
    let (_, coverage, _) = journal
        .query(&request, Instant::now() + Duration::from_secs(2), 0)
        .unwrap();
    let mut end = request;
    end.cursor = Some(AuditCursor(format!(
        "1:{}:{filter}:0000000000000001:0000000000000001",
        coverage.epoch
    )));
    assert!(journal.query(&end, Instant::now(), 0).is_err());
}

#[cfg(unix)]
fn policies(n: usize) -> Vec<AuditPolicyIdentity> {
    (0..n)
        .map(|i| AuditPolicyIdentity {
            role: AuditPolicyRole::Admission,
            scope: format!("{i}{}", "s".repeat(127)),
            generation: 1,
            digest: digest(),
        })
        .collect()
}

#[cfg(unix)]
#[test]
fn lowered_record_cap_checks_envelope_before_any_slot_or_disk_side_effect() {
    let directory = Directory::new();
    let (handle, mut worker) = open(
        directory.0.join("audit"),
        AuditLimits {
            maximum_record_bytes: 4096,
            ..Default::default()
        },
    )
    .unwrap();
    let mut large = attempt();
    large.actor.subject = "a".repeat(512);
    large.scope = AuditScope::Tenant(TenantId("t".repeat(512)));
    let candidate = (0..=8)
        .find_map(|n| {
            let mut candidate = large.clone();
            candidate.identities.policies = policies(n);
            (codec::encode(&candidate, 4096).is_ok()
                && codec::envelope(
                    &candidate.scope,
                    &candidate.actor,
                    AuditRecordData::Attempt(candidate.clone()),
                    4096,
                )
                .is_err())
            .then_some(candidate)
        })
        .expect("bounded inner attempt fits while envelope exceeds cap");
    assert!(handle.try_reserve_critical(&candidate).is_err());
    let event = (0..=8)
        .find_map(|n| {
            let mut event = observation(large.scope.clone());
            event.actor = large.actor.clone();
            event.identities.policies = policies(n);
            (codec::encode(&event, 4096).is_ok()
                && codec::envelope(
                    &event.scope,
                    &event.actor,
                    AuditRecordData::Observation(event.clone()),
                    4096,
                )
                .is_err())
            .then_some(event)
        })
        .expect("bounded inner observation fits while envelope exceeds cap");
    assert!(handle.try_capture(&event).is_err());
    let snapshot = handle.snapshot();
    assert_eq!(snapshot.retained_records, 0);
    assert_eq!(snapshot.reserved_records, 0);
    assert_eq!(snapshot.pending_attempts, 0);
    stop(&handle, &mut worker);
}

#[cfg(unix)]
#[test]
fn oversized_terminal_envelope_falls_back_to_owned_unknown_and_shutdown_finishes() {
    let mut source = attempt();
    source.actor.subject = "a".repeat(512);
    source.scope = AuditScope::Tenant(TenantId("t".repeat(512)));
    let terminal = (0..=8)
        .find_map(|n| {
            let mut terminal = conclusion();
            terminal.identities.policies = policies(n);
            terminal.identities.rollout = Some("r".repeat(256));
            terminal.identities.deployment = Some(latent_core::DeploymentId("d".repeat(256)));
            terminal.identities.revision = Some(latent_core::RevisionId("v".repeat(256)));
            (codec::encode(&terminal, 4096).is_ok()
                && codec::envelope(
                    &source.scope,
                    &source.actor,
                    AuditRecordData::Outcome {
                        attempt_sequence: 1,
                        conclusion: terminal.clone(),
                    },
                    4096,
                )
                .is_err())
            .then_some(terminal)
        })
        .expect("conclusion can fit while final envelope exceeds cap");
    codec::conclusion(&terminal).unwrap();
    let directory = Directory::new();
    let (handle, mut worker) = open(
        directory.0.join("audit"),
        AuditLimits {
            maximum_record_bytes: 4096,
            ..Default::default()
        },
    )
    .unwrap();
    let mut active = handle
        .try_reserve_critical(&source)
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    active.mutation_started().unwrap();
    assert!(active.finish(terminal).blocking_wait().is_err());
    stop(&handle, &mut worker);
    assert_eq!(handle.snapshot().unknown_outcomes, 1);
    assert_eq!(handle.snapshot().pending_attempts, 0);
    assert_eq!(handle.snapshot().reserved_records, 0);
}

#[cfg(unix)]
#[test]
fn first_start_creates_bounded_private_ancestors_without_following_links() {
    use std::os::unix::fs::{symlink, MetadataExt};
    let directory = Directory::new();
    let node = directory.0.join("node");
    let child = node.join("nested");
    let (handle, mut worker) = open(child.join("audit"), AuditLimits::default()).unwrap();
    for path in [&node, &child, &child.join("audit")] {
        let metadata = std::fs::symlink_metadata(path).unwrap();
        assert_eq!(metadata.mode() & 0o7777, 0o700);
        assert_eq!(metadata.uid(), rustix::process::geteuid().as_raw());
    }
    stop(&handle, &mut worker);
    let link = directory.0.join("link");
    symlink(&child, &link).unwrap();
    assert!(open(link.join("uncreated/audit"), AuditLimits::default()).is_err());
    assert!(!child.join("uncreated").exists());
    let excessive = directory
        .0
        .join("must-stay-absent")
        .join("a/".repeat(128))
        .join("audit");
    assert!(open(excessive, AuditLimits::default()).is_err());
    assert!(!directory.0.join("must-stay-absent").exists());
}
