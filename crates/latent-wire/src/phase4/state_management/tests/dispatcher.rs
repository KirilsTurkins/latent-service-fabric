use super::*;
use crate::management::{LocalManagementPolicy, ManagementDecision, ManagementOperation};
use latent_core::{
    native_capacity::{NativeCapacityLimits, NativeCapacityOwner},
    InvocationPrincipal, Metadata, PrincipalKind, TenantId,
};
use latent_effects::{
    authority::{EffectAuthorityOwner, EffectTime},
    runtime::{DispatcherConfig, DispatcherOwner},
};
use latent_rpc::control::v1::dispatcher_service_server::DispatcherService;
use std::sync::Mutex;

fn operator(subject: &str) -> AuthenticatedInvocationContext {
    AuthenticatedInvocationContext::new(InvocationPrincipal {
        subject: subject.into(),
        kind: PrincipalKind::Administrator,
        tenant: Some(TenantId("a".into())),
        service: None,
        claims: Metadata::from([("latent.node.operator".into(), "true".into())]),
    })
}
async fn install(fixture: &mut Fixture) -> (DispatcherOwner, NativeCapacityOwner) {
    let capacity = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    super::recovery::install(fixture, capacity.clone());
    let owner = DispatcherOwner::start(
        DispatcherConfig {
            start_paused: true,
            ..DispatcherConfig::default()
        },
        Arc::clone(&fixture.store),
        EffectAuthorityOwner::new(16, 4, 4).unwrap(),
        vec![],
        Arc::new(|| EffectTime {
            unix_millis: 100,
            continuity_proven: true,
        }),
        None,
    )
    .await
    .unwrap();
    Arc::get_mut(&mut fixture.backend.0).unwrap().dispatcher = Some(owner.management_port());
    (owner, capacity)
}
fn control(
    owner: &DispatcherOwner,
    operation: &str,
    action: c::DispatcherAction,
) -> c::ControlDispatcherRequest {
    let generation = owner.snapshot().unwrap().control.generation;
    c::ControlDispatcherRequest {
        profile: Some(contract::current_profile()),
        scope: c::DispatcherScope::Node as i32,
        operation_id: operation.into(),
        action: action as i32,
        expected_generation: Some(c::DispatcherGeneration {
            owner_epoch: generation.owner_epoch(),
            revision: generation.revision(),
        }),
    }
}
async fn assert_node_audit(
    fixture: &Fixture,
    action: latent_audit::AuditControlAction,
    result: latent_audit::AuditOperationResult,
) {
    let page = fixture
        .audit
        .as_ref()
        .unwrap()
        .0
        .query(
            latent_audit::AuditQueryRequest {
                scope: latent_audit::AuditScope::Node,
                filter: latent_audit::AuditFilter::default(),
                limit: 16,
                maximum_bytes: 65536,
                cursor: None,
            },
            deadline(),
        )
        .unwrap()
        .wait()
        .await
        .unwrap();
    assert!(page.records().iter().any(|row|matches!(&row.data,latent_audit::AuditRecordData::Attempt(value) if value.action==action && value.identities.dispatcher.as_ref().unwrap().actor_tenant=="a")));
    assert!(page.records().iter().any(|row|matches!(&row.data,latent_audit::AuditRecordData::Outcome {conclusion,..} if conclusion.result==result && conclusion.receipt_digest.is_some()==(result==latent_audit::AuditOperationResult::Committed))));
    // The accepted conclusion precedes this actual journal query. Its persisted
    // outcome is the readiness witness for another critical audit reservation.
    assert_eq!(
        fixture
            .audit
            .as_ref()
            .unwrap()
            .0
            .snapshot()
            .reserved_records,
        0
    );
}
#[tokio::test]
async fn actual_authenticated_dispatcher_receipt_is_historical_and_audit_failure_cannot_mutate() {
    let mut fixture = Fixture::new(true).await;
    let (mut owner, capacity) = install(&mut fixture).await;
    let adapter = super::super::super::Phase4ServiceAdapter::with_services(
        Arc::new(fixture.backend.clone()),
        crate::management::ManagementLimits::default(),
        super::super::super::Phase4Services {
            principals: Arc::new(crate::invocation::LocalPrincipalPolicy),
            management: Arc::clone(&fixture.backend.0.services.authorization),
            clock: Arc::new(latent_core::SystemActivationClock),
        },
    )
    .unwrap();
    let inspected = adapter
        .inspect_dispatcher(operator("alice").request(c::InspectDispatcherRequest {
            profile: Some(contract::current_profile()),
            scope: c::DispatcherScope::Node as i32,
        }))
        .await
        .unwrap();
    assert!(inspected.get_ref().dispatcher.as_ref().unwrap().paused);
    assert_eq!(capacity.snapshot().unwrap().recovery.slots, 1);
    drop(inspected);
    let original = control(&owner, "original-resume", c::DispatcherAction::Resume);
    let resumed = adapter
        .control_dispatcher(operator("alice").request(original.clone()))
        .await
        .unwrap();
    assert!(resumed.get_ref().published && !resumed.get_ref().paused);
    assert_eq!(
        resumed.get_ref().audit_ack.as_ref().unwrap().status,
        c::AuditAckStatus::Durable as i32
    );
    owner.pause();
    let lookup = c::GetDispatcherOperationRequest {
        original: Some(original),
    };
    let recovered = adapter
        .get_dispatcher_operation(operator("alice").request(lookup.clone()))
        .await
        .unwrap();
    assert_eq!(recovered.get_ref().receipt, resumed.get_ref().receipt);
    assert!(owner.snapshot().unwrap().paused);
    assert_eq!(
        adapter
            .get_dispatcher_operation(operator("bob").request(lookup))
            .await
            .err()
            .unwrap()
            .code(),
        tonic::Code::NotFound
    );
    assert_node_audit(
        &fixture,
        latent_audit::AuditControlAction::DispatcherResume,
        latent_audit::AuditOperationResult::Committed,
    )
    .await;
    fixture.audit.as_ref().unwrap().0.close();
    let generation = owner.snapshot().unwrap().control.generation;
    assert_eq!(
        adapter
            .control_dispatcher(operator("alice").request(control(
                &owner,
                "audit-denied",
                c::DispatcherAction::Pause,
            )))
            .await
            .err()
            .unwrap()
            .code(),
        tonic::Code::Unavailable
    );
    assert_eq!(owner.snapshot().unwrap().control.generation, generation);
    drop(resumed);
    drop(recovered);
    assert!(capacity.snapshot().unwrap().physically_retired());
    assert!(owner.shutdown(deadline()).await.unwrap().clean);
    fixture.finish().await;
}

#[derive(Clone)]
struct RevocablePolicy(Arc<Mutex<(u64, bool)>>);
struct OriginalDecision {
    state: Arc<Mutex<(u64, bool)>>,
    generation: u64,
}
impl RevocablePolicy {
    fn change(&self, enabled: bool) {
        let mut state = self.0.lock().unwrap();
        state.0 = state.0.checked_add(1).unwrap();
        state.1 = enabled;
    }
}
impl ManagementPolicy for RevocablePolicy {
    fn authorize(
        &self,
        principal: &InvocationPrincipal,
        operation: ManagementOperation,
    ) -> Result<(), PlatformError> {
        LocalManagementPolicy.authorize(principal, operation)?;
        if !self.0.lock().unwrap().1 {
            return Err(denied());
        }
        Ok(())
    }
    fn retain_node_control(
        &self,
        principal: &InvocationPrincipal,
    ) -> Result<Arc<dyn ManagementDecision>, PlatformError> {
        LocalManagementPolicy.authorize(principal, ManagementOperation::NodeControl)?;
        let state = self.0.lock().unwrap();
        if !state.1 {
            return Err(denied());
        }
        Ok(Arc::new(OriginalDecision {
            state: Arc::clone(&self.0),
            generation: state.0,
        }))
    }
}
impl ManagementDecision for OriginalDecision {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let state = self.state.lock().unwrap();
        if !state.1 || state.0 != self.generation {
            return Err(denied());
        }
        action()
    }
}
#[tokio::test]
async fn dispatcher_original_policy_is_captured_before_poll_and_reallow_cannot_revive_it() {
    let mut fixture = Fixture::new(true).await;
    let (mut owner, capacity) = install(&mut fixture).await;
    let policy = RevocablePolicy(Arc::new(Mutex::new((1, true))));
    Arc::get_mut(&mut fixture.backend.0)
        .unwrap()
        .services
        .authorization = Arc::new(policy.clone());
    let original = control(&owner, "never-accepted", c::DispatcherAction::Pause);
    let future = fixture
        .backend
        .execute_state(operator("alice"), original.clone().into());
    assert_eq!(capacity.snapshot().unwrap().recovery.slots, 1);
    policy.change(false);
    policy.change(true);
    assert_eq!(
        future.await.err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(capacity.snapshot().unwrap().recovery.slots, 0);
    assert_eq!(owner.snapshot().unwrap().control.generation.revision(), 1);
    assert_eq!(
        fixture
            .backend
            .execute_state(
                operator("alice"),
                c::GetDispatcherOperationRequest {
                    original: Some(original)
                }
                .into(),
            )
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::NotFound
    );
    assert_node_audit(
        &fixture,
        latent_audit::AuditControlAction::DispatcherOperationRead,
        latent_audit::AuditOperationResult::Rejected,
    )
    .await;
    let original = control(&owner, "new-authorized", c::DispatcherAction::Pause);
    let committed = fixture
        .backend
        .execute_state(operator("alice"), original.clone().into())
        .await
        .unwrap();
    policy.change(false);
    assert!(committed
        .owner
        .with_current(&mut || panic!("revoked delivery"))
        .is_err());
    policy.change(true);
    assert!(committed
        .owner
        .with_current(&mut || panic!("old authority refreshed"))
        .is_err());
    let recovered = fixture
        .backend
        .execute_state(
            operator("alice"),
            c::GetDispatcherOperationRequest {
                original: Some(original),
            }
            .into(),
        )
        .await
        .unwrap();
    let (contract::Response::ControlDispatcher(a), contract::Response::GetDispatcherOperation(b)) =
        (&committed.response, &recovered.response)
    else {
        panic!("associated dispatcher responses")
    };
    assert_eq!(a.receipt, b.receipt);
    drop(committed);
    drop(recovered);
    assert!(capacity.snapshot().unwrap().physically_retired());
    assert!(owner.shutdown(deadline()).await.unwrap().clean);
    fixture.finish().await;
}
