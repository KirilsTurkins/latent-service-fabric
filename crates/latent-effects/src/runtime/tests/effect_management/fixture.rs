use super::*;
use crate::dispatch_store::effect_management::{
    EffectManagementAction, EffectManagementCatalog, EffectManagementInput, EffectManagementPlan,
    EffectManagementRequest,
};
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservation,
    NativeReservationRequest,
};
use latent_core::{StateNamespaceId, TenantId};
use latent_state::namespace::{namespace_record_key, NamespaceQuota, NamespaceRecord};

pub(super) struct Access {
    pub allowed: Arc<AtomicBool>,
    permit: NativeReservation,
}
impl EffectManagementAuthorization for Access {
    fn before_lookup(&self) -> Result<(), Error> {
        if !self.allowed.load(Ordering::Acquire) {
            return Err(Error::PermissionDenied);
        }
        self.permit.with_live(|| ()).map_err(|_| Error::Closed)
    }
    fn original_deadline(&self) -> Instant {
        self.permit.original_deadline()
    }
    fn with_current(
        &self,
        namespace: &latent_state::namespace::catalog::NamespaceRead,
        _phase: EffectManagementPhase,
        _action: EffectManagementAction,
        accept: &mut dyn FnMut() -> Result<(), Error>,
    ) -> Result<(), Error> {
        if !self.allowed.load(Ordering::Acquire)
            || namespace.record().tenant.0 != "tenant-a"
            || namespace.record().version.incarnation != 7
        {
            return Err(Error::PermissionDenied);
        }
        accept()
    }
    fn with_live(&self, accept: &mut dyn FnMut() -> Result<(), Error>) -> Result<(), Error> {
        self.permit.with_live(accept).map_err(|_| Error::Closed)?
    }
}
pub(super) fn global() -> NativeCapacityOwner {
    NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap()
}
pub(super) fn access(global: &NativeCapacityOwner) -> Arc<Access> {
    Arc::new(Access {
        allowed: Arc::new(AtomicBool::new(true)),
        permit: global
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 16 * 1024,
                    work_bytes: 8 * 1024 * 1024,
                    response_bytes: 1024 * 1024,
                },
                Instant::now() + Duration::from_secs(30),
            )
            .unwrap(),
    })
}

pub(super) struct LookupAdapter {
    profile: DispatchProfile,
    pub gates: Rendezvous,
    entered: tokio::sync::mpsc::Sender<Event>,
    pub lookups: Arc<AtomicUsize>,
    pub sends: Arc<AtomicUsize>,
    pub positive: AtomicBool,
}
impl LookupAdapter {
    pub fn new() -> (Arc<Self>, tokio::sync::mpsc::Receiver<Event>) {
        let (entered, receiver) = tokio::sync::mpsc::channel(4);
        (
            Arc::new(Self {
                profile: profile("lookup.v1"),
                gates: Rendezvous::new(4),
                entered,
                lookups: Arc::new(AtomicUsize::new(0)),
                sends: Arc::new(AtomicUsize::new(0)),
                positive: AtomicBool::new(true),
            }),
            receiver,
        )
    }
}
impl DeferredEffectAdapter for LookupAdapter {
    fn profile(&self) -> &DispatchProfile {
        &self.profile
    }
    fn accept(
        &self,
        grant: DispatchGrant,
        _payload: PayloadRecord,
        _attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        grant.require_execution()?;
        self.sends.fetch_add(1, Ordering::SeqCst);
        Err(AuthorityError::Unavailable)
    }
    fn accept_reconciliation(
        &self,
        grant: DispatchGrant,
        request: ProviderReconciliationRequest,
    ) -> Result<BoxFuture<'static, ProviderReconciliationOutcome>, AuthorityError> {
        assert_eq!(
            grant.purpose(),
            crate::authority::DispatchPurpose::ReconcileOnly
        );
        request.payload().verify_grant(&grant)?;
        assert_eq!(request.attempt().attempt(), grant.attempt());
        let effect = grant.effect().to_owned();
        let (payload, attempt, version) = request.into_parts();
        let (registration, mut tracked) = self.gates.track((payload, grant)).unwrap();
        let gates = self.gates.clone();
        let entered = self.entered.clone();
        let lookups = Arc::clone(&self.lookups);
        let positive = self.positive.load(Ordering::Acquire);
        Ok(Box::pin(async move {
            lookups.fetch_add(1, Ordering::SeqCst);
            tracked.commit(Stage::Entered).unwrap();
            let mut paused = Box::pin(tracked.pause());
            PollProbe::default().pending(paused.as_mut());
            let ticket = gates.blocked(registration, Stage::Entered).unwrap();
            entered
                .send(Event {
                    effect,
                    registration,
                    ticket: Some(ticket),
                })
                .await
                .unwrap();
            paused.await;
            drop(tracked);
            if positive {
                ProviderReconciliationOutcome::Confirmed(
                    ProviderConfirmation::new(
                        attempt,
                        version,
                        "positive-original-provider-receipt".into(),
                        101,
                    )
                    .unwrap(),
                )
            } else {
                ProviderReconciliationOutcome::Uncertain(ProviderReconciliationReason::NotFound)
            }
        }))
    }
}

pub(super) async fn setup() -> (
    Fixture,
    DispatcherOwner,
    DurableEffectAuthority,
    Arc<LookupAdapter>,
    tokio::sync::mpsc::Receiver<Event>,
) {
    setup_with_send(true).await
}

pub(super) async fn setup_with_send(
    send_started: bool,
) -> (
    Fixture,
    DispatcherOwner,
    DurableEffectAuthority,
    Arc<LookupAdapter>,
    tokio::sync::mpsc::Receiver<Event>,
) {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(1, "tenant-a", "original-publication", profile("lookup.v1"))
        .await;
    let mut namespace = NamespaceRecord::create(
        TenantId("tenant-a".into()),
        StateNamespaceId("orders".into()),
        format!("sha256:{}", "a".repeat(64)),
        NamespaceQuota::default(),
    )
    .unwrap();
    namespace.version.incarnation = 7;
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: latent_state::embedded::RowKey {
                    family: latent_state::embedded::Family::Namespace,
                    key: namespace_record_key(&namespace.tenant, &namespace.id).unwrap(),
                },
                value: Some(namespace.encode().unwrap()),
            }],
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let (adapter, entered) = LookupAdapter::new();
    let dispatcher = fixture
        .start(
            DispatcherConfig {
                start_paused: true,
                ..config()
            },
            vec![adapter.clone()],
            None,
        )
        .await
        .unwrap();
    complete_original(&fixture, &authority, &dispatcher, send_started).await;
    fixture.clock.millis.store(101, Ordering::SeqCst);
    (fixture, dispatcher, authority, adapter, entered)
}

async fn complete_original(
    fixture: &Fixture,
    authority: &DurableEffectAuthority,
    dispatcher: &DispatcherOwner,
    send_started: bool,
) {
    let original = authority.clone();
    let epoch = dispatcher.services.epoch;
    fixture
        .store
        .with_store(StoreIoKind::Write, 2 * 1024 * 1024, move |store| {
            let due = initial_due_mutation(&original).unwrap();
            let due =
                crate::dispatch_store::DueRecord::decode(&due.key, due.value.as_deref().unwrap())?;
            let claimed = DispatchCatalog::claim(
                store,
                epoch,
                &due,
                EffectTime {
                    unix_millis: 100,
                    continuity_proven: true,
                },
            )
            .unwrap();
            if send_started {
                DispatchCatalog::begin_send(
                    store,
                    epoch,
                    &claimed.attempt,
                    EffectTime {
                        unix_millis: 100,
                        continuity_proven: true,
                    },
                )
                .unwrap();
            }
            DispatchCatalog::complete(
                store,
                epoch,
                &claimed.attempt,
                AttemptReceipt {
                    disposition: if send_started {
                        Disposition::Uncertain
                    } else {
                        Disposition::KnownFailed
                    },
                    reason: if send_started {
                        "original-lost-ack"
                    } else {
                        "original-affirmative-nonexecution"
                    }
                    .into(),
                    provider_receipt: None,
                    observed_at_millis: 100,
                },
                None,
                EffectTime {
                    unix_millis: 100,
                    continuity_proven: true,
                },
            )
            .unwrap();
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

pub(super) async fn request(
    fixture: &Fixture,
    authority: &DurableEffectAuthority,
    action: EffectManagementAction,
    operation: &str,
) -> EffectManagementRequest {
    let effect = authority.link().effect.clone();
    let version = fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, 128 * 1024, move |store| {
            let bytes = store
                .snapshot()?
                .get(&effect_row_key(&effect).unwrap())?
                .unwrap();
            Ok(crate::dispatch::effect_record_version(&bytes).unwrap())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    EffectManagementRequest::new(EffectManagementInput {
        actor_tenant: "tenant-a".into(),
        actor_subject: "operator-a".into(),
        namespace: "orders".into(),
        incarnation: 7,
        caller_scope: "caller-a".into(),
        command: authority.link().command.clone(),
        command_attempt: 1,
        effect: authority.link().effect.clone(),
        operation_id: operation.into(),
        action,
        expected_version: version,
        expected_policy_digest: format!("sha256:{}", "b".repeat(64)),
        original_request_digest: [2; 32],
        reason: "explicit reviewed operation".into(),
        retry_delay_millis: u64::from(action == EffectManagementAction::Redrive),
    })
    .unwrap()
}
pub(super) async fn plan(
    port: &DispatcherManagementPort,
    request: EffectManagementRequest,
    access: &Arc<Access>,
) -> EffectManagementPlan {
    let result = port
        .plan_effect_retained(request, access.clone(), (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    match result.outcome.unwrap() {
        EffectManagementOutcome::Plan { plan, .. } => plan,
        _ => panic!("expected plan"),
    }
}
pub(super) async fn receipt(
    fixture: &Fixture,
    plan: &EffectManagementPlan,
) -> Option<crate::dispatch_store::effect_management::EffectManagementReceipt> {
    let plan = plan.clone();
    fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, 128 * 1024, move |store| {
            Ok(EffectManagementCatalog::lookup(&store.snapshot()?, &plan).unwrap())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}
