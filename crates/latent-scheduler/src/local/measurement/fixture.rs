use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_admission::{
    AdmissionPermit, AdmissionRequest, CellClassPolicy, DeadlinePolicy, LocalAdmissionController,
    LocalQuotaProvider, NodeAdmissionPolicy, NodeLoadSnapshot, NodeLoadState, OverloadPolicy,
    QueueClassPolicy, QuotaLimits, QuotaUsage, TenantAdmissionPolicy, TrustClassPolicy,
};
use latent_core::{
    ActivationId, BoxFuture, ContractId, FunctionId, InvocationPrincipal, Metadata, NodeId,
    PlatformError, PlatformErrorCode, PrincipalKind, ReleaseDigest, ResourceBudget, RevisionId,
    RouteGeneration, ServiceId, TenantId,
};
use latent_routing::revision_policy::{
    ExecutionBackendKind, ExecutionRequirements, PlacementPolicy, StateModel, ThreadingModel,
};
use latent_routing::{
    InvocationTarget, ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource,
};
use tokio::sync::watch;

use crate::{CellClass, LocalScheduler, LocalSchedulerConfig, SchedulingCancellation};

use super::{platform, Result};

pub(in crate::local) fn id(ordinal: u32) -> ActivationId {
    ActivationId(format!("scheduler-{ordinal:05}"))
}

pub(super) fn tenant(index: u32) -> TenantId {
    TenantId(format!("tenant-{index:02}"))
}

fn names(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|name| (*name).to_owned()).collect()
}

fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 65_536,
        wall_time_limit_millis: Some(1_000),
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

fn revision(index: u32) -> ResolvedRevision {
    ResolvedRevision {
        target: InvocationTarget {
            tenant: tenant(index),
            service: ServiceId("scheduler".to_owned()),
            contract: ContractId("tests:scheduler/api@1.0.0".to_owned()),
            function: FunctionId("run".to_owned()),
            route: None,
        },
        revision: RevisionId(format!("revision-v1:sha256:{}", "a".repeat(64))),
        release: ReleaseDigest(format!("sha256:{}", "b".repeat(64))),
        route_generation: RouteGeneration(1),
        attributes: Metadata::new(),
    }
}

struct Source(BTreeMap<TenantId, ResolvedRevision>);

impl RevisionPolicySource for Source {
    fn admission_policy(
        &self,
        supplied: &ResolvedRevision,
    ) -> std::result::Result<RevisionAdmissionPolicy, PlatformError> {
        if self.0.get(&supplied.target.tenant) != Some(supplied) {
            return Err(PlatformError {
                code: PlatformErrorCode::RouteUnavailable,
                message: "unknown scheduler fixture revision".to_owned(),
                retryable: false,
                details: vec![],
            });
        }
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

pub(in crate::local) struct Cancellation {
    id: ActivationId,
    state: watch::Sender<bool>,
}

impl Cancellation {
    pub fn new(ordinal: u32) -> Arc<Self> {
        Arc::new(Self {
            id: id(ordinal),
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
                if receiver.changed().await.is_err() {
                    return;
                }
            }
        })
    }
}

pub(in crate::local) struct Fixture {
    pub scheduler: Arc<LocalScheduler>,
    pub quotas: LocalQuotaProvider,
    admission: LocalAdmissionController,
    revisions: Vec<ResolvedRevision>,
}

impl Fixture {
    pub fn new(tenants: u32, queue_capacity: u32) -> Result<Self> {
        let policy = policy(tenants);
        let quotas = LocalQuotaProvider::new(policy).map_err(platform)?;
        let revisions = (0..tenants).map(revision).collect::<Vec<_>>();
        let source = Source(
            revisions
                .iter()
                .map(|value| (value.target.tenant.clone(), value.clone()))
                .collect(),
        );
        let load = Arc::new(
            NodeLoadState::new(NodeLoadSnapshot {
                accepting: true,
                cpu_pressure_milli: 0,
                memory_pressure_milli: 0,
                queue_delay_millis: 0,
                observed_at: Instant::now(),
            })
            .map_err(platform)?,
        );
        let admission = LocalAdmissionController::new(Arc::new(source), quotas.clone(), load);
        let scheduler = Arc::new(
            LocalScheduler::new(
                LocalSchedulerConfig {
                    node: NodeId("scheduler-measurement".to_owned()),
                    queue_capacity_per_class: BTreeMap::from([(
                        CellClass::Standard,
                        queue_capacity,
                    )]),
                    starvation_after: Duration::from_millis(100),
                },
                quotas.clone(),
            )
            .map_err(platform)?,
        );
        Ok(Self {
            scheduler,
            quotas,
            admission,
            revisions,
        })
    }

    pub fn admit(
        &self,
        ordinal: u32,
        selected_tenant: u32,
    ) -> std::result::Result<AdmissionPermit, PlatformError> {
        let revision =
            self.revisions[usize::try_from(selected_tenant).expect("bounded tenant")].clone();
        self.admission.admit_now(AdmissionRequest {
            activation_id: id(ordinal),
            principal: InvocationPrincipal {
                subject: "scheduler-client".to_owned(),
                kind: PrincipalKind::User,
                tenant: Some(revision.target.tenant.clone()),
                service: None,
                claims: Metadata::new(),
            },
            revision,
            requested_budget: budget(),
            deadline_unix_millis: None,
            payload_bytes: 0,
            priority: 10,
            attributes: Metadata::new(),
        })
    }

    pub fn idle(&self) -> Result<()> {
        let observed = self.scheduler.observations(CellClass::Standard);
        if observed.available != 4
            || observed.active_leases != 0
            || observed.quarantined != 0
            || observed.queue_depth != 0
            || observed.queued_tenants != 0
            || self.quotas.usage().map_err(platform)? != QuotaUsage::default()
            || self.quotas.retained_tenant_count().map_err(platform)? != 0
        {
            return Err("scheduler owners did not return idle".into());
        }
        Ok(())
    }
}

fn policy(tenants: u32) -> NodeAdmissionPolicy {
    let limits = QuotaLimits {
        maximum_concurrent_activations: 68,
        maximum_queued_activations: 68,
        maximum_reserved_cpu_fuel: 6_800,
        maximum_reserved_memory_bytes: 68 * 65_536,
    };
    NodeAdmissionPolicy {
        budget_ceiling: budget(),
        limits,
        tenants: (0..tenants)
            .map(|index| {
                (
                    tenant(index),
                    TenantAdmissionPolicy {
                        limits,
                        maximum_payload_bytes: 1_024,
                        maximum_priority: 255,
                        allowed_subjects: names(&["scheduler-client"]),
                        allowed_principal_kinds: vec![PrincipalKind::User],
                        allowed_trust_classes: names(&["local"]),
                        allowed_cell_classes: names(&["standard"]),
                    },
                )
            })
            .collect(),
        trust_classes: BTreeMap::from([(
            "local".to_owned(),
            TrustClassPolicy {
                limits,
                allowed_cell_classes: names(&["standard"]),
            },
        )]),
        queue_classes: BTreeMap::from([(
            "default".to_owned(),
            QueueClassPolicy {
                minimum_priority: 0,
                maximum_priority: 255,
                maximum_queued_activations: 68,
            },
        )]),
        cell_classes: BTreeMap::from([(
            "standard".to_owned(),
            CellClassPolicy {
                maximum_memory_bytes: 65_536,
                parallelism: 4,
                threading_models: vec![ThreadingModel::SingleThreaded],
                features: BTreeSet::new(),
            },
        )]),
        maximum_payload_bytes: 1_024,
        maximum_priority: 255,
        maximum_identifier_bytes: 1_024,
        maximum_metadata_entries: 32,
        maximum_metadata_bytes: 4_096,
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
