//! One captured publication binds observations to the actual compiled cohort.
use super::super::{DirectoryDeploymentRepository, PublicationView};
use super::{prepare, table::StoredRollout};
use crate::rollouts::{
    codec, conflict, error, invalid, Result, RolloutCanaryDecision, RolloutCanaryPolicy, RolloutId,
    RolloutState, MAX_ROW_BYTES,
};
use latent_core::{PlatformErrorCode, RevisionId, TenantId};
use latent_manifest::__serde_json as json;
use latent_telemetry::phase2_canary::{
    BoundedPhase2CanaryOutcomeWindow, CanaryRevisionBinding, CanaryVerdict, CanaryWindowIdentity,
    CanaryWindowSpec, SealedCanaryWindow,
};
use std::{hash::BuildHasher, time::Duration};

/// Compact coherent control snapshot. It retains no route graph and grants no promotion.
#[derive(Debug)]
pub struct RolloutCanaryCohort {
    spec: CanaryWindowSpec,
    policy: RolloutCanaryPolicy,
    revision: u64,
    state_version: u64,
}
impl RolloutCanaryCohort {
    #[must_use]
    pub fn window_spec(&self) -> &CanaryWindowSpec {
        &self.spec
    }
    #[must_use]
    pub fn policy(&self) -> &RolloutCanaryPolicy {
        &self.policy
    }
    #[must_use]
    pub fn revision(&self) -> u64 {
        self.revision
    }
    #[must_use]
    pub fn state_version(&self) -> u64 {
        self.state_version
    }
    #[must_use]
    pub fn candidate_revision(&self) -> &RevisionId {
        &self.spec.revisions[1].revision
    }
    #[must_use]
    pub fn baseline_revision(&self) -> &RevisionId {
        &self.spec.revisions[0].revision
    }
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        let identity = &self.spec.identity;
        std::mem::size_of::<Self>()
            + identity.tenant.0.capacity()
            + identity.service.0.capacity()
            + identity.deployment.capacity()
            + identity.rollout_id.capacity()
            + 71
            + self.spec.revisions.capacity() * std::mem::size_of::<CanaryRevisionBinding>()
            + self
                .spec
                .revisions
                .iter()
                .map(|r| {
                    r.revision.0.capacity()
                        + r.component.0.capacity()
                        + r.package.as_ref().map_or(0, |p| p.as_str().len())
                })
                .sum::<usize>()
    }
}
impl DirectoryDeploymentRepository {
    pub fn with_canary(mut self, hub: BoundedPhase2CanaryOutcomeWindow) -> Result<Self> {
        if self.canary.is_some() {
            return Err(invalid());
        }
        self.canary = Some(hub);
        Ok(self)
    }
    #[must_use]
    pub fn canary_hub(&self) -> Option<&BoundedPhase2CanaryOutcomeWindow> {
        self.canary.as_ref()
    }
    pub fn rollout_canary_cohort(
        &self,
        tenant: &TenantId,
        id: &RolloutId,
        expected_revision: u64,
    ) -> Result<RolloutCanaryCohort> {
        crate::rollouts::validation::token(&tenant.0, 256)?;
        crate::rollouts::validation::token(&id.0, 128)?;
        let current = self.read_publication();
        let row = current
            .rollouts
            .row(tenant, id)
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "rollout-not-found"))?;
        if row.status.revision != expected_revision {
            return Err(conflict());
        }
        self.canary_cohort(&current, row)
    }
    pub(super) fn canary_cohort(
        &self,
        current: &PublicationView,
        row: &StoredRollout,
    ) -> Result<RolloutCanaryCohort> {
        if !current.confirmed {
            return Err(error(
                PlatformErrorCode::Unavailable,
                "rollout-durability-uncertain",
            ));
        }
        let status = &row.status;
        let policy = status.canary_policy.ok_or_else(invalid)?;
        if status.state != RolloutState::Running || !prepare::cohort_matches(&current.routes, row)?
        {
            return Err(conflict());
        }
        let mut revisions = Vec::with_capacity(2);
        for release in [&status.base, &status.candidate] {
            let record = current
                .routes
                .record_by_id(&release.deployment_id)
                .ok_or_else(conflict)?;
            if record.deployment.release != release.component {
                return Err(conflict());
            }
            revisions.push(CanaryRevisionBinding {
                revision: record.revision.clone(),
                component: release.component.clone(),
                package: release.package.clone(),
            });
        }
        let bindings:Vec<_>=revisions.iter().map(|r|json::json!({"revision":r.revision.0,"component":r.component.0,"package":r.package.as_ref().map(latent_core::PackageDigest::as_str)})).collect();
        let control = codec::hash(&codec::encode(
            &json::json!({"version":1,
            "owner":self.rollout_cursor_epoch,"nonce":self.pagination_fingerprint.hash_one(self.rollout_cursor_epoch),
            "tenant":status.tenant.0,"service":status.service.0,"rollout":status.id.0,
            "policy":policy.digest()?.as_str(),"plan":status.plan_digest.as_str(),
            "revision":status.revision,"step":status.current_step,"generation":current.routes.generation.0,
            "bindings":bindings,"cohort":row.cohort}),
            MAX_ROW_BYTES,
        )?);
        Ok(RolloutCanaryCohort {
            spec: CanaryWindowSpec {
                identity: CanaryWindowIdentity {
                    tenant: status.tenant.clone(),
                    service: status.service.clone(),
                    deployment: status.candidate.deployment_id.0.clone(),
                    rollout_id: status.id.0.clone(),
                    step: u64::from(status.current_step),
                    generation: current.routes.generation,
                },
                control_digest: Some(control),
                revisions,
                duration: Duration::from_millis(policy.observation_millis),
            },
            policy,
            revision: status.revision,
            state_version: current.transaction,
        })
    }
    pub(super) fn canary_decision(
        &self,
        current: &PublicationView,
        row: &StoredRollout,
        proof: &SealedCanaryWindow,
    ) -> Result<RolloutCanaryDecision> {
        let hub = self
            .canary
            .as_ref()
            .ok_or_else(|| error(PlatformErrorCode::Unavailable, "rollout-canary-unavailable"))?;
        let cohort = self.canary_cohort(current, row)?;
        let spec = cohort.window_spec();
        if !hub.owns_sealed(proof)
            || proof.identity() != &spec.identity
            || proof.control_digest() != spec.control_digest.as_ref()
            || proof.revisions() != spec.revisions
            || proof.duration() != spec.duration
        {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "rollout-canary-evidence-mismatch",
            ));
        }
        if proof
            .assess_candidate(cohort.candidate_revision(), cohort.policy.thresholds())?
            .verdict
            != CanaryVerdict::Healthy
        {
            return Err(error(
                PlatformErrorCode::StateConflict,
                "rollout-canary-not-healthy",
            ));
        }
        let mut decision = RolloutCanaryDecision {
            format_version: 1,
            policy_digest: cohort.policy.digest()?,
            control_digest: spec.control_digest.clone().ok_or_else(invalid)?,
            evidence_digest: codec::hash(b""),
            window_epoch: proof.epoch(),
            observed_millis: cohort.policy.observation_millis,
            baseline: proof.revision_outcomes()[0].into(),
            candidate: proof.revision_outcomes()[1].into(),
        };
        decision.evidence_digest = decision.evidence_hash()?;
        decision.validate(&cohort.policy)?;
        Ok(decision)
    }
}
