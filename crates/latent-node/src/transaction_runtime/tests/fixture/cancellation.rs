use super::*;
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::STATE_CONTRACT;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityOwner, NativeReservation, NativeReservationRequest,
};
use latent_core::PlatformError;
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, OwnedPolicyDecision, ResourceTarget,
};
use latent_state::namespace::catalog::NamespaceRead;
use std::sync::atomic::{AtomicBool, Ordering};

pub(in crate::transaction_runtime::tests) struct CancellationAuthority {
    policy: Arc<PolicyStore>,
    decision: Arc<OwnedPolicyDecision>,
    namespace: NamespaceRead,
    namespaces: Arc<NamespaceCatalog>,
    native: NativeReservation,
    cutoff: Instant,
    pub refused: AtomicBool,
}
impl super::super::super::CommandCancellationAuthority for CancellationAuthority {
    fn policy(&self) -> &PolicyStore {
        &self.policy
    }
    fn decision(&self) -> &Arc<OwnedPolicyDecision> {
        &self.decision
    }
    fn namespace(&self) -> &NamespaceRead {
        &self.namespace
    }
    fn namespaces(&self) -> &NamespaceCatalog {
        &self.namespaces
    }
    fn cutoff(&self) -> Result<Instant, PlatformError> {
        if self.refused.load(Ordering::SeqCst) {
            return Err(super::super::super::authorization::denied());
        }
        Ok(self.cutoff)
    }
    fn uses_native_capacity(&self, owner: &NativeCapacityOwner) -> bool {
        self.native.is_from_owner(owner)
    }
    fn with_native_until(
        &self,
        cutoff: Instant,
        action: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        if self.refused.load(Ordering::SeqCst) {
            return Err(super::super::super::authorization::denied());
        }
        self.native
            .with_live_until(cutoff.min(self.cutoff), action)
            .map_err(|_| super::super::super::authorization::denied())
    }
    fn with_native_pair_until(
        &self,
        other: &NativeReservation,
        cutoff: Instant,
        action: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        if self.refused.load(Ordering::SeqCst) {
            return Err(super::super::super::authorization::denied());
        }
        self.native
            .with_live_pair_until(other, cutoff.min(self.cutoff), action)
            .map_err(|_| super::super::super::authorization::denied())
    }
}
impl Fixture {
    pub(in crate::transaction_runtime::tests) async fn cancellation_authority(
        &self,
        envelope: &ActivationEnvelope,
        record: &latent_commit::atomic::CommandRecord,
        operation: &str,
        deadline: Instant,
    ) -> Arc<CancellationAuthority> {
        let namespace = self
            .store
            .with_store(StoreIoKind::Read, 8192, |store| {
                Ok(NamespaceCatalog::read_in(
                    &store.snapshot()?,
                    &latent_core::TenantId("a".into()),
                    &latent_core::StateNamespaceId("orders".into()),
                )
                .unwrap()
                .unwrap())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let binding = self.installation.state_binding_for_native_test();
        let snapshot = self
            .policy
            .snapshot(
                &envelope.target.tenant,
                &binding.policies,
                &binding.binding,
                deadline,
            )
            .unwrap();
        let input = EvaluationInput {
            principal: &envelope.principal,
            service: &envelope.target.service.0,
            publication: self.publication.publication().as_str(),
            capability: STATE_CONTRACT,
            operation,
            resource: ResourceTarget::State {
                namespace: &record.key().namespace,
                incarnation: 1,
                entity: record.key().entity.as_deref(),
                recovery_kind: latent_policy::capability::RecoveryScopeKind::OriginalCaller,
                recovery_scope: &record.key().recovery_scope,
                result_policy: record.result_read_policy(),
            },
        };
        let decision = snapshot
            .authorize(
                input,
                &CallRestrictions {
                    imported_operations: &binding.operations,
                    deployment: &binding.deployment,
                    provider_configuration: &binding.provider_configuration,
                    provider_profile: &binding.profile,
                    configuration_digest: &binding.configuration_digest,
                    configuration_epoch: binding.configuration_epoch,
                    remaining: CapabilityCeiling {
                        operations: 256,
                        input_bytes: 2_097_152,
                        output_bytes: 2_097_152,
                        wall_time_millis: 10_000,
                    },
                    input_bytes: 0,
                    output_bytes: 0,
                },
                &self.publication,
            )
            .unwrap();
        let decision = Arc::new(self.policy.retain_decision(&decision).unwrap());
        let native = self
            .native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 32 * 1024,
                    work_bytes: 256 * 1024,
                    response_bytes: 16 * 1024,
                },
                deadline,
            )
            .unwrap();
        Arc::new(CancellationAuthority {
            policy: self.policy.clone(),
            decision,
            namespace,
            namespaces: self.namespaces.clone(),
            native,
            cutoff: deadline,
            refused: AtomicBool::new(false),
        })
    }
}
