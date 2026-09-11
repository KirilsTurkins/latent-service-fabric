use std::collections::{BTreeMap, BTreeSet};
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use latent_admission::{
    AdmissionRequest, CellClassPolicy, DeadlinePolicy, LocalAdmissionController,
    LocalQuotaProvider, NodeAdmissionPolicy, NodeLoadSnapshot, NodeLoadState, OverloadPolicy,
    QueueClassPolicy, QuotaLimits, TenantAdmissionPolicy, TrustClassPolicy,
};
use latent_core::{
    ActivationClock, ActivationId, ClockSample, ContractId, FunctionId, InvocationPrincipal,
    Metadata, NodeId, PlatformError, PrincipalKind, ReleaseDigest, ResourceBudget, RevisionId,
    RouteGeneration, ServiceId, TenantId,
};
use latent_routing::revision_policy::{
    ExecutionBackendKind, ExecutionRequirements, PlacementPolicy, StateModel, ThreadingModel,
};
use latent_routing::{
    InvocationTarget, ResolvedBinding, ResolvedRevision, RevisionAdmissionPolicy,
    RevisionPolicySource, RouteResolver,
};
use latent_scheduler::{CellClass, LocalScheduler, LocalSchedulerConfig};

use super::super::{
    EmptyCacheInventorySource, NodeDescriptor, NodeTopologyEntry, NodeTopologySource,
    NodeTopologyWriter, ResourceOwnership, StandaloneInventorySources,
};

pub(super) struct Clock(pub Mutex<ClockSample>);
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        *self.0.lock().expect("clock")
    }
    fn monotonic_now(&self) -> Instant {
        self.sample().monotonic()
    }
}

pub(super) struct Routes {
    pub generation: AtomicU64,
    pub reads: AtomicUsize,
}

impl RouteResolver for Routes {
    fn generation(&self) -> RouteGeneration {
        self.reads.fetch_add(1, Ordering::Relaxed);
        RouteGeneration(self.generation.load(Ordering::Relaxed))
    }
    fn resolve(
        &self,
        _target: &InvocationTarget,
        _key: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError> {
        panic!("inventory must not resolve or scan a service catalog")
    }
    fn resolve_binding(
        &self,
        _consumer: &ResolvedRevision,
        _contract: &ContractId,
        _key: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError> {
        panic!("inventory must not resolve bindings")
    }
}

struct Policy;
impl RevisionPolicySource for Policy {
    fn admission_policy(
        &self,
        _revision: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        Ok(RevisionAdmissionPolicy {
            deployment_ceiling: budget(),
            execution: ExecutionRequirements {
                backend: ExecutionBackendKind::WasmComponent,
                threading: ThreadingModel::SingleThreaded,
                state_model: StateModel::Stateless,
                resource_budget_ceiling: budget(),
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

pub(super) struct Fixture {
    pub scheduler: Arc<LocalScheduler>,
    pub quotas: LocalQuotaProvider,
    pub clock: Arc<Clock>,
    pub load: Arc<NodeLoadState>,
    pub routes: Arc<Routes>,
    admission: LocalAdmissionController,
}

impl Fixture {
    pub fn new() -> Self {
        Self::with_queue_capacity(2)
    }

    pub fn with_queue_capacity(queue_capacity: u32) -> Self {
        let quotas = LocalQuotaProvider::new(policy()).expect("quota policy");
        let sample = ClockSample::new(1_700_000_000_000, Instant::now());
        let clock = Arc::new(Clock(Mutex::new(sample)));
        let load = Arc::new(
            NodeLoadState::new(NodeLoadSnapshot {
                accepting: true,
                cpu_pressure_milli: 100,
                memory_pressure_milli: 200,
                queue_delay_millis: 0,
                observed_at: sample.monotonic(),
            })
            .expect("load"),
        );
        let admission =
            LocalAdmissionController::new(Arc::new(Policy), quotas.clone(), load.clone());
        let scheduler = Arc::new(
            LocalScheduler::new(
                LocalSchedulerConfig {
                    node: NodeId("inventory-node".to_owned()),
                    queue_capacity_per_class: BTreeMap::from([(
                        CellClass::Standard,
                        queue_capacity,
                    )]),
                    starvation_after: Duration::from_secs(1),
                },
                quotas.clone(),
            )
            .expect("scheduler"),
        );
        Self {
            scheduler,
            quotas,
            clock,
            load,
            admission,
            routes: Arc::new(Routes {
                generation: AtomicU64::new(7),
                reads: AtomicUsize::new(0),
            }),
        }
    }

    pub fn sources(&self) -> StandaloneInventorySources {
        StandaloneInventorySources {
            scheduler: self.scheduler.clone(),
            routes: self.routes.clone(),
            quotas: self.quotas.clone(),
            load: self.load.clone(),
            cache: Arc::new(EmptyCacheInventorySource),
            topology: Arc::new(Topology),
            clock: self.clock.clone(),
        }
    }

    pub fn admit(&self, id: &str) -> latent_admission::AdmissionPermit {
        self.admission
            .admit_at(
                AdmissionRequest {
                    activation_id: ActivationId(id.to_owned()),
                    principal: InvocationPrincipal {
                        kind: PrincipalKind::User,
                        subject: "caller".to_owned(),
                        tenant: Some(TenantId("tenant".to_owned())),
                        service: None,
                        claims: Metadata::new(),
                    },
                    revision: ResolvedRevision {
                        target: InvocationTarget {
                            tenant: TenantId("tenant".to_owned()),
                            service: ServiceId("dormant-service-name".to_owned()),
                            contract: ContractId("test:inventory/api@1.0.0".to_owned()),
                            function: FunctionId("run".to_owned()),
                            route: None,
                        },
                        revision: RevisionId(format!("revision-v1:sha256:{}", "a".repeat(64))),
                        release: ReleaseDigest(format!("sha256:{}", "b".repeat(64))),
                        route_generation: RouteGeneration(7),
                        attributes: Metadata::new(),
                    },
                    requested_budget: budget(),
                    deadline_unix_millis: None,
                    payload_bytes: 0,
                    priority: 0,
                    attributes: Metadata::new(),
                },
                self.clock.sample(),
            )
            .expect("admission")
    }
}

fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 65_536,
        wall_time_limit_millis: Some(60_000),
        log_bytes: 16,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        effect_count: 0,
    }
}

fn policy() -> NodeAdmissionPolicy {
    let limits = QuotaLimits {
        maximum_concurrent_activations: 4,
        maximum_queued_activations: 4,
        maximum_reserved_cpu_fuel: 1000,
        maximum_reserved_memory_bytes: 1_048_576,
    };
    let classes = BTreeSet::from(["standard".to_owned()]);
    NodeAdmissionPolicy {
        budget_ceiling: budget(),
        limits,
        tenants: BTreeMap::from([(
            TenantId("tenant".to_owned()),
            TenantAdmissionPolicy {
                limits,
                maximum_payload_bytes: 1024,
                maximum_priority: 255,
                allowed_subjects: BTreeSet::from(["caller".to_owned()]),
                allowed_principal_kinds: vec![PrincipalKind::User],
                allowed_trust_classes: BTreeSet::from(["local".to_owned()]),
                allowed_cell_classes: classes.clone(),
            },
        )]),
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
                maximum_queued_activations: 4,
            },
        )]),
        cell_classes: BTreeMap::from([(
            "standard".to_owned(),
            CellClassPolicy {
                maximum_memory_bytes: 65_536,
                parallelism: 1,
                threading_models: vec![ThreadingModel::SingleThreaded],
                features: BTreeSet::new(),
            },
        )]),
        maximum_payload_bytes: 1024,
        maximum_priority: 255,
        maximum_identifier_bytes: 512,
        maximum_metadata_entries: 16,
        maximum_metadata_bytes: 4096,
        overload: OverloadPolicy {
            maximum_cpu_pressure_milli: 900,
            maximum_memory_pressure_milli: 900,
            maximum_sample_age_millis: 5000,
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

pub(super) fn node() -> NodeDescriptor {
    NodeDescriptor {
        id: NodeId("inventory-node".to_owned()),
        architecture: "x86_64".to_owned(),
        operating_system: "test".to_owned(),
        cpu_features: vec![],
        trust_classes: vec!["local".to_owned()],
        region: None,
        zone: None,
        endpoint: "local://inventory".to_owned(),
        identity: "node-owned".to_owned(),
        attributes: Metadata::new(),
    }
}

struct Topology;
impl NodeTopologySource for Topology {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        writer.push(&NodeTopologyEntry {
            name: "fixed-node-process".to_owned(),
            kind: "process".to_owned(),
            ownership: ResourceOwnership::NodeFixed,
            configured_count: 1,
            active_count: Some(1),
            attributes: Metadata::new(),
        })
    }
}
