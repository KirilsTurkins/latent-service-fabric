//! The existing signed package fixture supplies real current namespace policy seals.
use crate::standalone::state::SignedFixture;
use latent_artifacts::{AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository};
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};
use latent_policy::{
    capability::{
        CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, MutationRequest,
        OwnedPolicyDecision, PolicyStore, PolicyStoreLimits, RecordKind, ResourceTarget,
    },
    supply_chain::SupplyChainAuthority,
};
use latent_state::embedded::StoreError;
use serde_json::json;
use std::{path::Path, sync::Arc};

pub(super) struct Gate {
    pub policy: Arc<PolicyStore>,
    pub publication: String,
    pub component: String,
    decision: OwnedPolicyDecision,
    _artifacts: Arc<DirectoryArtifactRepository>,
    _authority: Arc<SupplyChainAuthority>,
}

impl Gate {
    #[expect(
        clippy::too_many_lines,
        reason = "One real signed package and exact state-purpose decision retains its original currentness owners"
    )]
    pub async fn new(directory: &Path, profile: &str, digest: &str) -> Self {
        let signed = SignedFixture::new();
        let authority = Arc::new(
            SupplyChainAuthority::open(
                &directory.join("trust"),
                signed.approved(),
                signed.clock.clone(),
                5,
            )
            .unwrap(),
        );
        let artifacts = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                directory.join("artifacts"),
                latent_artifacts::DirectoryArtifactRepositoryConfig::default(),
                AdmissionStorageLimits::default(),
                authority.clone(),
            )
            .unwrap(),
        );
        let admitted = artifacts
            .admit_package(&TenantId("tests".into()), signed.upload(), &mut |_| Ok(()))
            .await
            .unwrap();
        let publication = admitted.publication.as_ref().unwrap();
        let eligible = artifacts
            .execution_eligibility_selected(&admitted.descriptor.release_digest, Some(publication))
            .unwrap()
            .unwrap();
        let policy = Arc::new(
            PolicyStore::open(
                &directory.join("policy"),
                PolicyStoreLimits::default(),
                artifacts.lifecycle_authority(),
            )
            .unwrap(),
        );
        let principal = InvocationPrincipal {
            subject: "operator".into(),
            kind: PrincipalKind::Administrator,
            tenant: Some(TenantId("tests".into())),
            service: None,
            claims: Metadata::new(),
        };
        let caller = latent_capabilities::namespace::CallerScope::derive(
            &principal,
            &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
        )
        .unwrap();
        let contract = latent_capabilities::namespace::STATE_CONTRACT;
        let grant = json!({"formatVersion":1,"tenant":"tests","rules":[{
            "id":"resume","effect":"allow","principals":[{"kind":"administrator","subject":"operator"}],
            "services":["tests/packaging"],"publications":[publication.as_str()],"capability":contract,
            "operations":["namespace-resume"],"resources":{"kind":"state","scopes":[{
                "namespace":"business","incarnation":1,"entity":null,"recoveryKind":"original-caller",
                "recoveryScope":caller.scope,"resultPolicy":"visibility-v1"}]},
            "ceiling":{"operations":1,"inputBytes":1_048_576,"outputBytes":1_048_576,"wallTimeMillis":30_000}}]});
        let binding = json!({"formatVersion":1,"tenant":"tests","capability":contract,
            "providerProfile":profile,"configurationDigest":digest,"configurationEpoch":1,
            "restriction":{"operations":[]}});
        for (id, kind, document) in [
            ("resume", RecordKind::Policy, grant),
            ("original", RecordKind::ProviderBinding, binding),
        ] {
            let bytes = serde_json::to_vec(&document).unwrap();
            policy
                .mutate(
                    MutationRequest {
                        tenant: "tests",
                        actor: "operator",
                        id,
                        kind,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&bytes),
                    },
                    super::deadline(),
                    |_| Ok(()),
                )
                .unwrap();
        }
        let snapshot = policy
            .snapshot(
                &TenantId("tests".into()),
                &["resume".into()],
                "original",
                super::deadline(),
            )
            .unwrap();
        let unrestricted = GrantRestriction {
            operations: vec![],
            resources: None,
            ceiling: None,
        };
        let decision = snapshot
            .authorize(
                EvaluationInput {
                    principal: &principal,
                    service: "tests/packaging",
                    publication: publication.as_str(),
                    capability: contract,
                    operation: "namespace-resume",
                    resource: ResourceTarget::State {
                        namespace: "business",
                        incarnation: 1,
                        entity: None,
                        recovery_kind: caller.kind,
                        recovery_scope: &caller.scope,
                        result_policy: "visibility-v1",
                    },
                },
                &CallRestrictions {
                    imported_operations: &["namespace-resume".into()],
                    deployment: &unrestricted,
                    provider_configuration: &unrestricted,
                    provider_profile: profile,
                    configuration_digest: digest,
                    configuration_epoch: 1,
                    remaining: CapabilityCeiling {
                        operations: 1,
                        input_bytes: 1_048_576,
                        output_bytes: 1_048_576,
                        wall_time_millis: 30_000,
                    },
                    input_bytes: 0,
                    output_bytes: 0,
                },
                &eligible,
            )
            .unwrap();
        let decision = policy.retain_decision(&decision).unwrap();
        Self {
            policy,
            publication: publication.as_str().into(),
            component: admitted.descriptor.release_digest.0,
            decision,
            _artifacts: artifacts,
            _authority: authority,
        }
    }

    pub fn check(&self) -> Result<(), StoreError> {
        self.policy
            .with_retained_decision(&self.decision, &mut |_, _| Ok(()))
            .map_err(|_| StoreError::Unavailable)
    }

    pub fn deny(&self) {
        let expected_revision = {
            let current = self
                .policy
                .get(
                    "tests",
                    RecordKind::Policy,
                    "resume",
                    16 * 1024,
                    super::deadline(),
                )
                .unwrap();
            current.value().as_ref().unwrap().revision
        };
        self.policy
            .mutate(
                MutationRequest {
                    tenant: "tests",
                    actor: "operator",
                    id: "resume",
                    kind: RecordKind::Policy,
                    operation_id: "deny-resume",
                    expected_revision,
                    document: None,
                },
                super::deadline(),
                |_| Ok(()),
            )
            .unwrap();
        assert!(self
            .policy
            .snapshot(
                &TenantId("tests".into()),
                &["resume".into()],
                "original",
                super::deadline()
            )
            .is_err());
        assert_eq!(self.check(), Err(StoreError::Unavailable));
    }
}
