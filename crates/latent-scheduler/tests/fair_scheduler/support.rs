use std::collections::{BTreeMap, BTreeSet};
use std::future::poll_fn;
use std::sync::Arc;
use std::task::{Context, Poll, Waker};
use std::time::Duration;

use latent_admission::{
    AdmissionRequest, CellClassPolicy, DeadlinePolicy, LocalAdmissionController,
    LocalQuotaProvider, NodeAdmissionPolicy, NodeLoadSnapshot, NodeLoadState, OverloadPolicy,
    QueueClassPolicy, QuotaLimits, QuotaUsage, TenantAdmissionPolicy, TrustClassPolicy,
};
use latent_core::{
    ActivationId, BoxFuture, ClockSample, ContractId, FunctionId, InvocationPrincipal, Metadata,
    NodeId, PlatformError, PlatformErrorCode, PrincipalKind, ReleaseDigest, ResourceBudget,
    RevisionId, RouteGeneration, ServiceId, TenantId,
};
use latent_routing::revision_policy::{
    ExecutionBackendKind, ExecutionRequirements, PlacementPolicy, StateModel, ThreadingModel,
};
use latent_routing::{
    InvocationTarget, ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource,
};
use latent_scheduler::{
    AdmittedSchedulingRequest, CellClass, LocalScheduler, LocalSchedulerConfig,
    ScheduledActivation, SchedulingCancellation,
};
use tokio::sync::watch;

pub type Pending<'a> = BoxFuture<'a, Result<ScheduledActivation, PlatformError>>;

fn names(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|value| (*value).to_owned()).collect()
}

fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 65_536,
        wall_time_limit_millis: Some(60_000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 16,
        effect_count: 0,
    }
}

fn revision(tenant: &str) -> ResolvedRevision {
    ResolvedRevision {
        target: InvocationTarget {
            tenant: TenantId(tenant.to_owned()),
            service: ServiceId("echo".to_owned()),
            contract: ContractId("tests:scheduler/api@1.0.0".to_owned()),
            function: FunctionId("echo".to_owned()),
            route: None,
        },
        revision: RevisionId(format!("revision-v1:sha256:{}", "a".repeat(64))),
        release: ReleaseDigest(format!("sha256:{}", "b".repeat(64))),
        route_generation: RouteGeneration(1),
        attributes: Metadata::new(),
    }
}

struct Source(ResourceBudget);

impl RevisionPolicySource for Source {
    fn admission_policy(
        &self,
        supplied: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        if !["a", "b", "c"]
            .iter()
            .any(|tenant| *supplied == revision(tenant))
        {
            return Err(PlatformError {
                code: PlatformErrorCode::RouteUnavailable,
                message: "unknown test revision".to_owned(),
                retryable: false,
                details: vec![],
            });
        }
        Ok(RevisionAdmissionPolicy {
            deployment_ceiling: self.0.clone(),
            execution: ExecutionRequirements {
                backend: ExecutionBackendKind::WasmComponent,
                threading: ThreadingModel::SingleThreaded,
                state_model: StateModel::Stateless,
                resource_budget_ceiling: self.0.clone(),
                host_call_depth_maximum: 8,
                component_call_depth_maximum: 8,
                snapshot_eligible: false,
                fusion_eligible: false,
            },
            placement: PlacementPolicy {
                trust_class: "local".to_owned(),
                architectures: vec!["x86_64".to_owned()],
                regions: vec![],
                zones: vec![],
                required_features: vec![],
            },
        })
    }
}

pub struct Cancellation {
    id: ActivationId,
    state: watch::Sender<bool>,
}

impl Cancellation {
    pub fn new(id: &str) -> Arc<Self> {
        Arc::new(Self {
            id: ActivationId(id.to_owned()),
            state: watch::channel(false).0,
        })
    }
}

impl SchedulingCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }

    fn is_cancelled(&self) -> bool {
        *self.state.borrow()
    }

    fn request_cancellation(&self) -> bool {
        !self.state.send_replace(true)
    }

    fn cancelled(&self) -> BoxFuture<'_, ()> {
        Box::pin(async move {
            let mut receiver = self.state.subscribe();
            loop {
                if *receiver.borrow_and_update() {
                    return;
                }
                receiver.changed().await.expect("test sender remains alive");
            }
        })
    }
}

fn node_policy(
    class_specs: &[(&str, CellClass, u64, u32)],
    allow_extra_large: bool,
) -> NodeAdmissionPolicy {
    let limits = QuotaLimits {
        maximum_concurrent_activations: 128,
        maximum_queued_activations: 128,
        maximum_reserved_cpu_fuel: 1_000_000,
        maximum_reserved_memory_bytes: 512 * 1024 * 1024,
    };
    let mut ceiling = budget();
    ceiling.memory_bytes = class_specs
        .iter()
        .map(|(_, _, memory, _)| *memory)
        .max()
        .unwrap();
    let classes = class_specs
        .iter()
        .map(|(name, _, _, _)| (*name).to_owned())
        .collect::<BTreeSet<_>>();
    let mut tenant_classes = classes.clone();
    if !allow_extra_large {
        tenant_classes.remove("extra-large");
    }
    NodeAdmissionPolicy {
        budget_ceiling: ceiling.clone(),
        limits,
        tenants: ["a", "b", "c"]
            .into_iter()
            .map(|tenant| {
                (
                    TenantId(tenant.to_owned()),
                    TenantAdmissionPolicy {
                        limits,
                        maximum_payload_bytes: 1024,
                        maximum_priority: 255,
                        allowed_subjects: names(&["local-client"]),
                        allowed_principal_kinds: vec![PrincipalKind::User],
                        allowed_trust_classes: names(&["local"]),
                        allowed_cell_classes: tenant_classes.clone(),
                    },
                )
            })
            .collect(),
        trust_classes: BTreeMap::from([(
            "local".to_owned(),
            TrustClassPolicy {
                limits,
                allowed_cell_classes: classes,
            },
        )]),
        queue_classes: BTreeMap::from([(
            "default".to_owned(),
            QueueClassPolicy {
                minimum_priority: 0,
                maximum_priority: 255,
                maximum_queued_activations: 128,
            },
        )]),
        cell_classes: class_specs
            .iter()
            .map(|&(name, _, maximum_memory_bytes, parallelism)| {
                (
                    name.to_owned(),
                    CellClassPolicy {
                        maximum_memory_bytes,
                        parallelism,
                        threading_models: vec![ThreadingModel::SingleThreaded],
                        features: BTreeSet::new(),
                    },
                )
            })
            .collect(),
        maximum_payload_bytes: 1024,
        maximum_priority: 255,
        maximum_identifier_bytes: 1024,
        maximum_metadata_entries: 32,
        maximum_metadata_bytes: 4096,
        overload: OverloadPolicy {
            maximum_cpu_pressure_milli: 900,
            maximum_memory_pressure_milli: 900,
            maximum_sample_age_millis: u64::MAX,
        },
        deadline: DeadlinePolicy {
            estimated_service_time_millis: 1,
            minimum_execution_time_millis: 1,
            safety_margin_millis: 0,
        },
        architecture: "x86_64".to_owned(),
        region: None,
        zone: None,
    }
}

pub struct Fixture {
    pub scheduler: Arc<LocalScheduler>,
    pub quotas: LocalQuotaProvider,
    pub configuration: LocalSchedulerConfig,
    admission: LocalAdmissionController,
    initial_unix_millis: u64,
    initial_monotonic: tokio::time::Instant,
}

impl Fixture {
    pub fn new(tiny_capacity: u32, queue_capacity: u32, starvation_after: Duration) -> Self {
        Self::build(
            tiny_capacity,
            queue_capacity,
            starvation_after,
            false,
            false,
        )
    }

    pub fn with_all_classes(queue_capacity: u32, allow_extra_large: bool) -> Self {
        Self::build(
            2,
            queue_capacity,
            Duration::from_secs(1),
            true,
            allow_extra_large,
        )
    }

    fn build(
        tiny_capacity: u32,
        queue_capacity: u32,
        starvation_after: Duration,
        all_classes: bool,
        allow_extra_large: bool,
    ) -> Self {
        let mut class_specs = vec![
            ("tiny", CellClass::Tiny, 65_536, tiny_capacity),
            ("small", CellClass::Small, 262_144, 1),
        ];
        if all_classes {
            class_specs.extend([
                ("standard", CellClass::Standard, 1_048_576, 3),
                ("large", CellClass::Large, 4_194_304, 1),
                ("extra-large", CellClass::ExtraLarge, 8_388_608, 2),
            ]);
        }
        let policy = node_policy(&class_specs, allow_extra_large);
        let ceiling = policy.budget_ceiling.clone();
        let quotas = LocalQuotaProvider::new(policy).unwrap();
        let load = Arc::new(
            NodeLoadState::new(NodeLoadSnapshot {
                accepting: true,
                cpu_pressure_milli: 0,
                memory_pressure_milli: 0,
                queue_delay_millis: 0,
                observed_at: tokio::time::Instant::now().into_std(),
            })
            .unwrap(),
        );
        let admission =
            LocalAdmissionController::new(Arc::new(Source(ceiling)), quotas.clone(), load);
        let configuration = LocalSchedulerConfig {
            node: NodeId("fair-test-node".to_owned()),
            queue_capacity_per_class: class_specs
                .iter()
                .map(|(_, class, _, _)| (*class, queue_capacity))
                .collect(),
            starvation_after,
        };
        let scheduler =
            Arc::new(LocalScheduler::new(configuration.clone(), quotas.clone()).unwrap());
        Self {
            scheduler,
            quotas,
            configuration,
            admission,
            initial_unix_millis: ClockSample::system_now().unix_millis(),
            initial_monotonic: tokio::time::Instant::now(),
        }
    }

    pub fn request(&self, id: &str, tenant: &str) -> AdmittedSchedulingRequest {
        self.custom_request(id, tenant, 10, 60_000, 65_536).0
    }

    pub fn custom_request(
        &self,
        id: &str,
        tenant: &str,
        priority: u8,
        wall_millis: u64,
        memory: u64,
    ) -> (AdmittedSchedulingRequest, Arc<Cancellation>) {
        self.try_custom_request(id, tenant, priority, wall_millis, memory)
            .unwrap()
    }

    pub fn try_custom_request(
        &self,
        id: &str,
        tenant: &str,
        priority: u8,
        wall_millis: u64,
        memory: u64,
    ) -> Result<(AdmittedSchedulingRequest, Arc<Cancellation>), PlatformError> {
        let mut requested_budget = budget();
        requested_budget.memory_bytes = memory;
        requested_budget.wall_time_limit_millis = Some(wall_millis);
        let now = tokio::time::Instant::now();
        let elapsed_millis =
            u64::try_from(now.duration_since(self.initial_monotonic).as_millis()).unwrap();
        let permit = self.admission.admit_at(
            AdmissionRequest {
                activation_id: ActivationId(id.to_owned()),
                principal: InvocationPrincipal {
                    subject: "local-client".to_owned(),
                    kind: PrincipalKind::User,
                    tenant: Some(TenantId(tenant.to_owned())),
                    service: None,
                    claims: Metadata::new(),
                },
                revision: revision(tenant),
                requested_budget,
                deadline_unix_millis: None,
                payload_bytes: 4,
                priority,
                attributes: Metadata::new(),
            },
            ClockSample::new(self.initial_unix_millis + elapsed_millis, now.into_std()),
        )?;
        let cancellation = Cancellation::new(id);
        Ok((
            AdmittedSchedulingRequest {
                permit,
                cancellation: cancellation.clone(),
            },
            cancellation,
        ))
    }

    pub fn assert_no_quota(&self) {
        assert_eq!(self.quotas.usage().unwrap(), QuotaUsage::default());
        assert_eq!(self.quotas.retained_tenant_count().unwrap(), 0);
    }
}

pub fn register(future: &mut Pending<'_>) {
    assert!(future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
}

pub async fn complete(future: Pending<'_>) -> ScheduledActivation {
    tokio::time::timeout(Duration::from_secs(2), future)
        .await
        .expect("scheduler completion must be bounded")
        .expect("schedule accepted activation")
}

pub async fn next(pending: &mut Vec<Pending<'_>>) -> ScheduledActivation {
    let (index, result) = tokio::time::timeout(
        Duration::from_secs(2),
        poll_fn(|context| {
            for (index, future) in pending.iter_mut().enumerate() {
                if let Poll::Ready(result) = future.as_mut().poll(context) {
                    return Poll::Ready((index, result));
                }
            }
            Poll::Pending
        }),
    )
    .await
    .expect("one queued activation must become ready");
    drop(pending.remove(index));
    result.expect("queued activation must succeed")
}

pub async fn failure(future: Pending<'_>) -> PlatformErrorCode {
    match tokio::time::timeout(Duration::from_secs(2), future)
        .await
        .expect("rejection must be bounded")
    {
        Err(error) => error.code,
        Ok(_) => panic!("expected scheduler rejection"),
    }
}
