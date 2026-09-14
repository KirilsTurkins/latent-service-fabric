use super::*;
use latent_audit::*;
use latent_core::{BudgetDimension, TenantId};
use std::time::Instant;

struct Journal {
    handle: AuditHandle,
    worker: AuditWorker,
    _dir: tempfile::TempDir,
}
impl Journal {
    fn new(maximum_records: usize) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let (handle, worker) = DirectoryPhase2AuditJournal::open(
            dir.path().join("audit"),
            AuditLimits {
                maximum_records,
                ..Default::default()
            },
        )
        .unwrap();
        Self {
            handle,
            worker,
            _dir: dir,
        }
    }
    fn stop(&mut self) {
        self.handle.close();
        assert!(self
            .worker
            .join_until(Instant::now() + Duration::from_secs(2))
            .unwrap());
    }
    async fn query(&self, tenant: &str) -> AuditPage {
        let request = AuditQueryRequest {
            scope: AuditScope::Tenant(TenantId(tenant.into())),
            filter: AuditFilter::default(),
            cursor: None,
            limit: 32,
            maximum_bytes: 32768,
        };
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            match self.handle.query(request.clone(), deadline) {
                Err(error) if error.message == "audit-busy" && Instant::now() < deadline => {
                    tokio::task::yield_now().await
                }
                result => return result.unwrap().wait().await.unwrap(),
            }
        }
    }
    async fn drained(&self) {
        let deadline = Instant::now() + Duration::from_secs(2);
        while self.handle.snapshot().reserved_records != 0 && Instant::now() < deadline {
            tokio::task::yield_now().await;
        }
        assert_eq!(self.handle.snapshot().reserved_records, 0);
    }
}
impl Drop for Journal {
    fn drop(&mut self) {
        self.handle.close();
        let joined = self
            .worker
            .join_until(Instant::now() + Duration::from_secs(3));
        if !std::thread::panicking() {
            assert!(matches!(joined, Ok(true)));
        }
    }
}
async fn accepted(
    session: &CapabilitySession,
    handle: GuestCapabilityHandle,
) -> OwnedCapabilityResponse {
    session
        .call(
            handle,
            "read",
            resource(),
            b"sensitive-request",
            output(),
            |mut call| async move {
                call.record_provider_outcome(AuditProviderOutcome::SecretResolved)
                    .unwrap();
                call.complete(b"secret-value")
            },
        )
        .await
        .unwrap()
}

#[tokio::test]
async fn required_calls_have_exact_redacted_records_and_no_synchronous_bypass() {
    let journal = Journal::new(32);
    let f = Fixture::audited(
        CapabilityBrokerLimits::default(),
        journal.handle.clone(),
        true,
        false,
    );
    let (request, control) = f.request("audit-activation");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let dispatched = std::cell::Cell::new(false);
    assert!(session
        .dispatch(
            handle,
            "read",
            resource(),
            b"sensitive-request",
            output(),
            |_| dispatched.set(true)
        )
        .is_err());
    assert!(!dispatched.get());
    assert_eq!(journal.handle.snapshot().retained_records, 0);
    let response = accepted(&session, handle).await;
    assert_eq!(response.bytes(), b"secret-value");
    assert!(matches!(
        response.audit_durability(),
        CapabilityAuditDurability::Durable { .. }
    ));
    let page = journal.query("a").await;
    assert_eq!(page.records().len(), 2);
    let AuditRecordData::Attempt(attempt) = &page.records()[0].data else {
        panic!("attempt")
    };
    let context = attempt.identities.capability.as_ref().unwrap();
    assert_eq!(context.activation, "audit-activation");
    assert_eq!(context.root_activation, "audit-activation");
    assert_eq!(context.binding.id, "binding");
    assert_eq!(context.binding.revision, 3);
    assert_eq!(context.policies[0].id, "p");
    assert_eq!(context.policies[0].revision, 2);
    assert_eq!(context.provider_configuration_epoch, 1);
    assert_eq!(
        attempt.identities.publication.as_ref(),
        Some(f.publication.publication())
    );
    assert_eq!(
        attempt.identities.deployment.as_ref().unwrap().0,
        "echo-deployment"
    );
    let encoded = serde_json::to_string(page.records()).unwrap();
    for secret in ["sensitive-request", "secret-value", "test-key"] {
        assert!(!encoded.contains(secret));
    }
    drop(page);
    assert!(journal.query("another-tenant").await.records().is_empty());
    drop(response);
    session.close();
    drop(session);
    assert_eq!(f.broker.snapshot().calls, 0);
    assert_eq!(f.broker.snapshot().buffer_bytes, 0);
    assert_eq!(f.broker.snapshot().handles, 0);
}

#[tokio::test]
async fn full_audit_sink_refuses_new_effects_and_refunds_uncommitted_cost() {
    let journal = Journal::new(2);
    let f = Fixture::audited(
        CapabilityBrokerLimits::default(),
        journal.handle.clone(),
        true,
        false,
    );
    let (request, control) = f.request("full-sink");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    drop(accepted(&session, handle).await);
    let before = control.budget.snapshot_at(Instant::now()).log_bytes;
    let mut dispatched = false;
    let result = session
        .dispatch_audited(
            handle,
            "read",
            resource(),
            b"second",
            output().with_charge(BudgetDimension::LogBytes, 8).unwrap(),
            |_| {
                dispatched = true;
            },
        )
        .await;
    assert!(result.is_err());
    assert!(!dispatched);
    assert_eq!(control.budget.snapshot_at(Instant::now()).log_bytes, before);
    assert_eq!(f.broker.snapshot().calls, 0);
    assert_eq!(journal.handle.snapshot().retained_records, 2);
}

#[tokio::test]
async fn authority_changes_after_durable_begin_prevent_actual_dispatch() {
    for revoke_policy in [false, true] {
        let journal = Journal::new(32);
        let f = std::sync::Arc::new(Fixture::audited(
            CapabilityBrokerLimits::default(),
            journal.handle.clone(),
            true,
            false,
        ));
        let (request, control) = f.request("changed-during-audit");
        let session = f.session(&request, &control);
        let handle = session.bind(CAP, "read", resource()).unwrap();
        let change = f.clone();
        super::super::audit::set_after_begin(move || {
            if revoke_policy {
                change
                    .policies
                    .mutate(
                        latent_policy::capability::MutationRequest {
                            tenant: "a",
                            actor: "operator",
                            id: "p",
                            kind: latent_policy::capability::RecordKind::Policy,
                            operation_id: "revoke-after-begin",
                            expected_revision: 2,
                            document: None,
                        },
                        Instant::now() + Duration::from_secs(2),
                        |_| Ok(()),
                    )
                    .unwrap();
            } else {
                change.provider.retire();
            }
        });
        let mut dispatched = false;
        assert!(session
            .dispatch_audited(handle, "read", resource(), b"request", output(), |_| {
                dispatched = true;
            })
            .await
            .is_err());
        assert!(!dispatched);
        journal.drained().await;
        let page = journal.query("a").await;
        assert_eq!(page.records().len(), 2);
        let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
            panic!("outcome")
        };
        assert_eq!(conclusion.result, AuditOperationResult::NotStarted);
        assert_eq!(f.broker.snapshot().calls, 0);
    }
}

#[tokio::test]
async fn accepted_provider_with_failed_terminal_record_is_not_reported_as_denied() {
    let mut journal = Journal::new(32);
    let f = Fixture::audited(
        CapabilityBrokerLimits::default(),
        journal.handle.clone(),
        true,
        false,
    );
    let (request, control) = f.request("terminal-loss");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let mut call = session
        .dispatch_audited(handle, "read", resource(), b"request", output(), |call| {
            call
        })
        .await
        .unwrap();
    call.record_provider_outcome(AuditProviderOutcome::SecretResolved)
        .unwrap();
    // Make the next journal staging path unusable after the attempt is durable
    // and the provider has accepted. This works even for root-runner tests.
    std::fs::create_dir(journal._dir.path().join("audit/record.next")).unwrap();
    let mut response = call.complete(b"secret-value").unwrap();
    assert_eq!(
        response.finish_audit().await,
        CapabilityAuditDurability::OutcomeUnknown
    );
    assert_eq!(
        response.provider_outcome(),
        Some(AuditProviderOutcome::SecretResolved)
    );
    assert_eq!(response.bytes(), b"secret-value");
    assert!(journal.handle.snapshot().recovery_pending);
    journal.stop();
    std::fs::remove_dir(journal._dir.path().join("audit/record.next")).unwrap();
    let (handle, worker) = DirectoryPhase2AuditJournal::open(
        journal._dir.path().join("audit"),
        AuditLimits {
            maximum_records: 32,
            ..Default::default()
        },
    )
    .unwrap();
    journal.handle = handle;
    journal.worker = worker;
    reconcile_capability_audit(&journal.handle, Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert_eq!(journal.handle.snapshot().pending_attempts, 0);
    assert_eq!(journal.handle.snapshot().unknown_outcomes, 1);
    let page = journal.query("a").await;
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
        panic!("recovered outcome")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Unknown);
}

#[tokio::test]
async fn cancellation_keeps_unknown_outcome_and_real_provider_ownership() {
    let journal = Journal::new(32);
    let f = Fixture::audited(
        CapabilityBrokerLimits::default(),
        journal.handle.clone(),
        true,
        false,
    );
    let (request, control) = f.request("cancelled-provider");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let call = session
        .dispatch_audited(handle, "read", resource(), b"request", output(), |call| {
            call
        })
        .await
        .unwrap();
    control.probe.0.store(true, Ordering::Release);
    session.close();
    drop(session);
    assert_eq!(f.broker.snapshot().calls, 1);
    assert_ne!(f.broker.snapshot().buffer_bytes, 0);
    assert!(call.is_cancelled());
    drop(call); // Only actual provider cleanup releases this owner.
    journal.drained().await;
    assert_eq!(f.broker.snapshot().calls, 0);
    let page = journal.query("a").await;
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
        panic!("outcome")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Unknown);
    assert_eq!(
        conclusion
            .identities
            .capability
            .as_ref()
            .unwrap()
            .provider_outcome,
        Some(AuditProviderOutcome::Unknown)
    );
}

#[tokio::test]
async fn typed_inputs_need_their_actual_digest_and_optional_capture_stays_lossy() {
    let journal = Journal::new(2);
    let f = Fixture::audited(
        CapabilityBrokerLimits::default(),
        journal.handle.clone(),
        true,
        false,
    );
    let (request, control) = f.request("typed-request");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    assert!(session
        .dispatch_audited(
            handle,
            "read",
            resource(),
            &[],
            output().with_typed_input_bytes(8),
            |_| panic!("digest omission dispatched")
        )
        .await
        .is_err());
    let cost = output()
        .with_typed_input_bytes(8)
        .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[b"real-arg"]).unwrap());
    let mut call = session
        .dispatch_audited(handle, "read", resource(), &[], cost, |call| call)
        .await
        .unwrap();
    call.record_provider_outcome(AuditProviderOutcome::SecretResolved)
        .unwrap();
    call.finish_audit().await;
    drop(call);
    let other = Fixture::audited(
        CapabilityBrokerLimits::default(),
        journal.handle.clone(),
        false,
        true,
    );
    let (request, control) = other.request("optional-full");
    let session = other.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    assert_eq!(accepted(&session, handle).await.bytes(), b"secret-value");
    assert!(journal.handle.snapshot().dropped_observations > 0);
}

#[tokio::test]
async fn terminal_io_audit_releases_no_retained_buffer_or_activation_ownership() {
    use crate::broker::io::{IoLimits, IoRuntime};
    let journal = Journal::new(8);
    let f = Fixture::audited(
        CapabilityBrokerLimits::default(),
        journal.handle.clone(),
        true,
        false,
    );
    let (request, control) = f.request("io-audit");
    let session = f.session(&request, &control);
    let observer = session.observer();
    let io = IoRuntime::new(IoLimits::default()).unwrap();
    let ready = io.admit(&session).unwrap().wait().await.unwrap();
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let mut call = session
        .dispatch_audited(handle, "read", resource(), b"request", output(), |call| {
            ready.start(call)
        })
        .await
        .unwrap()
        .unwrap();
    session.close_handle(handle).unwrap();
    let mut buffer = call.buffer(32, 0).unwrap();
    buffer.spare_mut().unwrap()[0] = 42;
    buffer.advance_written(1).unwrap();
    let buffer = buffer.retain().unwrap();
    call.record_provider_outcome(AuditProviderOutcome::SecretResolved)
        .unwrap();
    let durability = call.finish_audit().await;
    assert!(matches!(
        durability,
        CapabilityAuditDurability::Durable { .. }
    ));
    assert_eq!(call.finish_audit().await, durability);
    assert_eq!(journal.query("a").await.records().len(), 2);
    drop(call);
    drop(session);
    assert_eq!(io.snapshot().result_bytes, 32);
    assert!(!observer.is_quiescent());
    drop(buffer);
    assert_eq!(io.snapshot().result_bytes, 0);
    assert!(observer.is_quiescent());
}
