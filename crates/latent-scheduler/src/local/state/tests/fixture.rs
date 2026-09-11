use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_admission::{
    AdmissionRequest, LocalAdmissionController, LocalQuotaProvider, NodeLoadSnapshot,
    NodeLoadState, QuotaUsage,
};
use latent_core::{
    ClockSample, InvocationPrincipal, Metadata, PrincipalKind, ResourceBudget, TenantId,
};
use latent_routing::revision_policy::{
    ExecutionBackendKind, ExecutionRequirements, PlacementPolicy, StateModel, ThreadingModel,
};
use latent_routing::{ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource};
use tokio::sync::oneshot;

use super::super::Entry;
use super::oracle::Key;
use crate::local::{measurement::fixture as common, AdmittedSchedulingRequest};

struct Source(ResourceBudget);
impl RevisionPolicySource for Source {
    fn admission_policy(
        &self,
        _: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, latent_core::PlatformError> {
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
                trust_class: "local".into(),
                architectures: vec!["x86_64".into()],
                regions: vec![],
                zones: vec![],
                required_features: vec![],
            },
        })
    }
}

pub(super) struct Fixture {
    pub quotas: LocalQuotaProvider,
    pub base: Instant,
    admission: LocalAdmissionController,
    revision: ResolvedRevision,
    budget: ResourceBudget,
}
impl Fixture {
    pub fn new(tenants: u32) -> Self {
        let original = common::Fixture::new(tenants, 64).unwrap();
        let permit = original.admit(0, 0).unwrap();
        let revision = permit.revision().clone();
        drop(permit);
        let mut policy = original.quotas.policy().clone();
        // Use real admitted deadlines with room for distinct and equal limits.
        // Admission requires a finite node ceiling; all other ceilings remain
        // those of the common fixture.
        policy.budget_ceiling.wall_time_limit_millis = Some(10_000);
        let budget = policy.budget_ceiling.clone();
        let quotas = LocalQuotaProvider::new(policy).unwrap();
        let base = Instant::now() + Duration::from_secs(1);
        let load = NodeLoadState::new(NodeLoadSnapshot {
            accepting: true,
            cpu_pressure_milli: 0,
            memory_pressure_milli: 0,
            queue_delay_millis: 0,
            observed_at: base,
        })
        .unwrap();
        let admission = LocalAdmissionController::new(
            Arc::new(Source(budget.clone())),
            quotas.clone(),
            Arc::new(load),
        );
        Self {
            quotas,
            base,
            admission,
            revision,
            budget,
        }
    }

    pub fn entry(&self, key: &Key) -> Entry {
        let mut budget = self.budget.clone();
        budget.wall_time_limit_millis = key
            .deadline
            .map(|deadline| u64::try_from(deadline.duration_since(self.base).as_millis()).unwrap());
        let mut revision = self.revision.clone();
        revision.target.tenant = tenant(key.tenant);
        let ordinal = u32::try_from(key.sequence).unwrap();
        let permit = self
            .admission
            .admit_at(
                AdmissionRequest {
                    activation_id: common::id(ordinal),
                    principal: InvocationPrincipal {
                        subject: "scheduler-client".into(),
                        kind: PrincipalKind::User,
                        tenant: Some(tenant(key.tenant)),
                        service: None,
                        claims: Metadata::new(),
                    },
                    revision,
                    requested_budget: budget,
                    deadline_unix_millis: None,
                    payload_bytes: 0,
                    priority: key.priority,
                    attributes: Metadata::new(),
                },
                ClockSample::new(10_000, self.base),
            )
            .unwrap();
        assert_eq!(permit.deadline().monotonic(), key.deadline);
        assert_eq!(permit.obligations().priority, key.priority);
        let (sender, _receiver) = oneshot::channel();
        Entry {
            sequence: key.sequence,
            request: AdmittedSchedulingRequest {
                permit,
                cancellation: common::Cancellation::new(ordinal),
            },
            enqueued_at: key.enqueued,
            sender,
        }
    }

    pub fn idle(&self) {
        assert_eq!(self.quotas.usage().unwrap(), QuotaUsage::default());
        assert_eq!(self.quotas.retained_tenant_count().unwrap(), 0);
    }
}

pub(super) fn tenant(index: u32) -> TenantId {
    TenantId(format!("tenant-{index:02}"))
}

pub(super) fn key(fixture: &Fixture, sequence: u64, selected_tenant: u32) -> Key {
    let index = usize::try_from(sequence - 1).unwrap();
    Key {
        sequence,
        tenant: selected_tenant,
        priority: [10, 255, 10, 0, 127][index % 5],
        enqueued: match index % 4 {
            0 => fixture
                .base
                .checked_sub(Duration::from_millis(100))
                .unwrap(),
            1 => fixture
                .base
                .checked_sub(Duration::from_millis(101))
                .unwrap(),
            2 => fixture.base,
            _ => fixture.base + Duration::from_millis(1),
        },
        deadline: Some(
            fixture.base
                + Duration::from_secs(match index % 4 {
                    0 => 10,
                    2 => 2,
                    _ => 5,
                }),
        ),
    }
}
