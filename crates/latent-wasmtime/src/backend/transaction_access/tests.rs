use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use latent_activation::{ActivationEnvelope, TraceContext};
use latent_core::transaction_contract::Value;
use latent_core::{
    ActivationBudget, ActivationId, BoxFuture, CellId, ClockSample, ContractId,
    EffectiveActivationBudget, FunctionId, InvocationPrincipal, Metadata, PrincipalKind,
    ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::transaction::{
    CommandInfo, Intent, IntentFailure, Mode, Page, RetainedTransfer, StateFailure,
    TransactionHost, VersionedValue, ViewIdentity,
};
use latent_executor::{
    ExecutionCancellation, ExecutionCell, ExecutionRequest, PreparationKey, PreparedComponent,
};
use latent_routing::InvocationTarget;

struct Host {
    id: ActivationId,
    budget: ActivationBudget,
    closed: AtomicUsize,
}

impl TransactionHost for Host {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn mode(&self) -> Mode {
        Mode::Query
    }
    fn budget(&self) -> &ActivationBudget {
        &self.budget
    }
    fn acquire(&self, _: Mode) -> Result<(), StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn release(&self, _: Mode) {
        panic!("no guest acquired this host")
    }
    fn view_identity(&self) -> Result<ViewIdentity, StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn command_info(&self) -> Result<CommandInfo, StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn authorize_read(&self) -> Result<(), StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn retain_transfer(&self, _: usize) -> Result<RetainedTransfer, StateFailure> {
        Err(StateFailure::PermissionDenied)
    }
    fn read(&self, _: Vec<u8>) -> BoxFuture<'_, Result<Option<VersionedValue>, StateFailure>> {
        Box::pin(async { Err(StateFailure::PermissionDenied) })
    }
    fn scan(
        &self,
        _: Vec<u8>,
        _: u32,
        _: Option<Vec<u8>>,
    ) -> BoxFuture<'_, Result<Page, StateFailure>> {
        Box::pin(async { Err(StateFailure::PermissionDenied) })
    }
    fn put(&self, _: Vec<u8>, _: Value) -> BoxFuture<'_, Result<(), StateFailure>> {
        Box::pin(async { Err(StateFailure::PermissionDenied) })
    }
    fn delete(&self, _: Vec<u8>) -> BoxFuture<'_, Result<(), StateFailure>> {
        Box::pin(async { Err(StateFailure::PermissionDenied) })
    }
    fn stage(&self, _: Intent) -> BoxFuture<'_, Result<u32, IntentFailure>> {
        Box::pin(async { Err(IntentFailure::PermissionDenied) })
    }
    fn finish_guest_access(&self) {
        self.closed.fetch_add(1, Ordering::SeqCst);
    }
}

struct Cancellation(Arc<Host>);
impl ExecutionCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.0.id
    }
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn transaction_host(&self) -> Option<Arc<dyn TransactionHost>> {
        Some(self.0.clone())
    }
}

fn resources() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 65536,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    }
}

fn host() -> Arc<Host> {
    let budget = resources();
    Arc::new(Host {
        id: ActivationId("transaction-pre-store".into()),
        budget: ActivationBudget::new(
            EffectiveActivationBudget::admit_at(
                &budget,
                &budget,
                &budget,
                None,
                ClockSample::new(1000, std::time::Instant::now()),
            )
            .unwrap(),
        ),
        closed: AtomicUsize::new(0),
    })
}

fn request(id: ActivationId) -> ExecutionRequest {
    let budget = resources();
    let target = InvocationTarget {
        tenant: TenantId("tenant".into()),
        service: ServiceId("service".into()),
        contract: ContractId("tests:generic/values@0.1.0".into()),
        function: FunctionId("query".into()),
        route: None,
    };
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: id.clone(),
            root_activation_id: id,
            parent_activation_id: None,
            principal: InvocationPrincipal {
                subject: "caller".into(),
                kind: PrincipalKind::User,
                tenant: Some(target.tenant.clone()),
                service: None,
                claims: Metadata::new(),
            },
            target,
            resolved_revision: None,
            deadline_unix_millis: None,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace".into()),
                span_id: SpanId("span".into()),
                trace_flags: 0,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: Metadata::new(),
            input: b"[]".to_vec(),
            input_media_type: crate::values::MEDIA_TYPE.into(),
        },
        prepared: PreparedComponent {
            backend: "foreign-backend".into(),
            opaque_handle: "unopened".into(),
            metadata: Metadata::new(),
            key: PreparationKey {
                publication: None,
                release: ReleaseDigest("release".into()),
                engine_version: "version".into(),
                engine_configuration_digest: "config".into(),
                target_triple: "target".into(),
                cpu_feature_set: "cpu".into(),
            },
        },
        cell: ExecutionCell {
            id: CellId("cell".into()),
            class: "standard".into(),
            maximum_memory_bytes: budget.memory_bytes,
            metadata: Metadata::new(),
        },
        imports: vec![],
        budget,
    }
}

#[tokio::test]
async fn refused_context_and_foreign_backend_close_actual_pre_store_guest_access() {
    for invalid_context in [false, true] {
        let config = crate::WasmtimeConfig::default();
        let context_bytes = config.maximum_artifact_metadata_bytes;
        let factory = crate::WasmtimeComponentEngineFactory::new(config).unwrap();
        let backend = factory.create_backend_instance();
        let host = host();
        let cancellation = Cancellation(host.clone());
        let mut request = request(host.id.clone());
        if invalid_context {
            request.activation.trace.trace_id.0 = "x".repeat(context_bytes + 1);
        }
        let report = backend.invoke_inner(request, &cancellation, None).await;
        let error = report.outcome.unwrap_err();
        if invalid_context {
            assert_eq!(
                error.code,
                latent_core::PlatformErrorCode::ResourceExhausted
            );
        } else {
            assert_eq!(error.code, latent_core::PlatformErrorCode::InvalidArgument);
            assert_eq!(
                error.message,
                "prepared component belongs to another execution backend"
            );
        }
        assert_eq!(host.closed.load(Ordering::SeqCst), 1);
        let snapshot = backend.resource_snapshot();
        assert_eq!(snapshot.stores_created, 0);
        assert_eq!(snapshot.live_stores, 0);
        assert_eq!(snapshot.live_host_states, 0);
        assert_eq!(snapshot.active_invocations, 0);
        drop(backend);
        factory.shutdown().unwrap();
    }
}

#[test]
fn transferred_access_closes_only_when_the_actual_host_state_access_is_destroyed() {
    let host = host();
    let cancellation = Cancellation(host.clone());
    let mut ownership = super::InvocationOwnership::new(&cancellation);
    let access =
        crate::host::transaction::Access::attach(ownership.transaction.take_host().unwrap());
    drop(ownership);
    assert_eq!(host.closed.load(Ordering::SeqCst), 0);
    drop(access);
    assert_eq!(host.closed.load(Ordering::SeqCst), 1);
}
