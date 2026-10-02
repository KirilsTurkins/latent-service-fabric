use super::{role::AdmissionTime, InstalledTransactionOperation, StateRuntime};
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{CallerScope, RecoverySelection};
use latent_commit::atomic::{
    AdmissionInput, CommandRecord, ReplayPolicy, ResultPolicy, SourceIdentity,
};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Precondition, Value},
    ActivationBudget, BoxFuture, PlatformError,
};
use latent_node::transaction_runtime::{
    command_completion::{
        CommandAdmissionFactory, CommandAdmissionSelection, CommandResultCodec, CommandRetry,
    },
    CommandTimeSource,
};
use latent_state::{
    session::{StateMode, StateScope},
    store_io::StoreIoKind,
};
use sha2::{Digest, Sha256};
use std::sync::Arc;

pub(super) struct Request {
    pub client_id: String,
    pub conditions: Vec<Precondition>,
    pub metadata: Vec<(String, String)>,
    pub retry: Option<CommandRetry>,
}
pub(super) struct Factory {
    pub runtime: StateRuntime,
    pub installed: Arc<InstalledTransactionOperation>,
    pub request: Request,
    pub codec: Arc<dyn CommandResultCodec>,
    pub time: Arc<AdmissionTime>,
}
impl CommandAdmissionFactory for Factory {
    fn preflight<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            self.runtime.accepts(&self.installed, envelope, budget)?;
            self.time.retain_admission(envelope, budget)?;
            let command =
                self.runtime
                    .retain(&self.installed, envelope, budget, "acquire-command")?;
            let result = self
                .runtime
                .retain(&self.installed, envelope, budget, "read-result")?;
            let (first, second) = self
                .runtime
                .namespaces(
                    &self.installed,
                    budget,
                    self.time.clone(),
                    StoreIoKind::Read,
                )
                .await?;
            // Sealing checks the actual coherent namespace and current policy;
            // this phase creates no fingerprint, role, claim or native session.
            self.runtime
                .seal(&self.installed, envelope, budget, first, command)?;
            self.runtime
                .seal(&self.installed, envelope, budget, second, result)?;
            Ok(())
        })
    }
    fn select<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<CommandAdmissionSelection, PlatformError>> {
        Box::pin(self.select_owned(envelope, budget))
    }
}
impl Factory {
    async fn select_owned(
        &self,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<CommandAdmissionSelection, PlatformError> {
        self.runtime.accepts(&self.installed, envelope, budget)?;
        self.time.retain_admission(envelope, budget)?;
        let command = self
            .runtime
            .retain(&self.installed, envelope, budget, "acquire-command")?;
        let result = self
            .runtime
            .retain(&self.installed, envelope, budget, "read-result")?;
        let (first, second) = self
            .runtime
            .namespaces(
                &self.installed,
                budget,
                self.time.clone(),
                StoreIoKind::Read,
            )
            .await?;
        let execution = self
            .runtime
            .seal(&self.installed, envelope, budget, first, command)?;
        let current_read = self
            .runtime
            .seal(&self.installed, envelope, budget, second, result)?;
        let key = command_key(&self.installed, envelope, self.request.client_id.clone())?;
        let mut original = self
            .runtime
            .coordinator(self.time.clone())
            .original_metadata(key.clone(), Arc::clone(&current_read))
            .await?;
        let original_read = if let Some(original) = &mut original {
            let op = self
                .runtime
                .original_operation(&self.installed, original.original_command())?;
            let decision = self.runtime.retain(&op, envelope, budget, "read-result")?;
            Some(
                self.runtime
                    .seal(&op, envelope, budget, original.take_namespace()?, decision)?,
            )
        } else {
            None
        };
        // The normal Node path supplies only the prepared component's actual
        // canonical typed bytes, under its original prepaid readiness pin.
        let fingerprint = self.fingerprint(envelope)?;
        let source = self.source(envelope)?;
        let owner_epoch = self.time.capture()?;
        let built = CommandAdmissionSelection::new(
            AdmissionInput {
                key,
                fingerprint,
                source,
                result_read_policy: self.installed.result_policy.clone(),
                result_policy: ResultPolicy {
                    replay: ReplayPolicy::Full,
                    maximum_result_bytes: 1_048_576,
                    result_millis: 86_400_000,
                    identity_millis: 604_800_000,
                    maximum_attempts: 16,
                },
                inbox: None,
                owner_epoch,
            },
            self.request.conditions.clone(),
            StateScope {
                tenant: self.installed.target.tenant.clone(),
                namespace: latent_core::StateNamespaceId(self.installed.namespace().into()),
                incarnation: self.installed.incarnation,
                state_schema: self.installed.state_schema().into(),
                entity: self.installed.entity.clone(),
                mode: StateMode::Command,
            },
            execution,
            current_read,
            Arc::clone(&self.codec),
        )
        .and_then(|selection| {
            let selection = match (original, original_read) {
                (Some(metadata), Some(read)) => {
                    selection.with_original_result_read(metadata, read)?
                }
                (None, None) => selection,
                _ => return Err(super::denied()),
            };
            if let Some(retry) = &self.request.retry {
                selection.with_retry(retry.clone())
            } else {
                Ok(selection)
            }
        });
        if built.is_err() {
            self.time.retire_without_claim();
        }
        built
    }
    fn source(&self, envelope: &ActivationEnvelope) -> Result<SourceIdentity, PlatformError> {
        let revision = envelope
            .resolved_revision
            .as_ref()
            .ok_or_else(super::denied)?;
        let source = SourceIdentity {
            publication: self.installed.publication.publication().to_string(),
            revision: revision.revision.0.clone(),
            release_digest: revision.release.0.clone(),
            component_digest: self.installed.publication.release().0.clone(),
            contract_digest: self.installed.contract_digest.clone(),
            route_generation: revision.route_generation.0,
            state_schema: self.installed.state_schema().into(),
            input_format: "lsf-wit-values-v1".into(),
            result_format: self.codec.format().into(),
        };
        source.validate().map_err(|_| super::denied())?;
        Ok(source)
    }

    fn fingerprint(
        &self,
        envelope: &ActivationEnvelope,
    ) -> Result<CommandFingerprint, PlatformError> {
        let mut metadata = self.request.metadata.clone();
        metadata.push((
            "transaction-binding".into(),
            self.installed.binding().into(),
        ));
        metadata.push((
            "transaction-contract".into(),
            self.installed.target.contract.0.clone(),
        ));
        let input = CommandFingerprint {
            input_format: "lsf-wit-values-v1".into(),
            input: Value {
                bytes: envelope.input.clone(),
                media_type: envelope.input_media_type.clone(),
                metadata,
            },
            expected_versions: self.request.conditions.clone(),
        };
        input
            .visit_identity_bytes(|_| ())
            .map_err(|_| super::capacity())?;
        Ok(input)
    }
}
pub(super) fn command_key(
    op: &InstalledTransactionOperation,
    envelope: &ActivationEnvelope,
    client_key: String,
) -> Result<CommandKey, PlatformError> {
    let caller = CallerScope::derive(&envelope.principal, &RecoverySelection::OriginalCaller)?;
    let mut digest = Sha256::new();
    digest.update(b"lsf-installed-operation-v1\0");
    for field in [
        &op.target.contract.0,
        &op.target.function.0,
        &op.companion.binding,
    ] {
        digest.update((field.len() as u64).to_le_bytes());
        digest.update(field.as_bytes());
    }
    let key = CommandKey {
        tenant: op.target.tenant.0.clone(),
        namespace: op.namespace().into(),
        incarnation: op.incarnation.to_string(),
        recovery_scope: caller.scope,
        operation: format!(
            "operation:sha256:{:x}",
            latent_core::digest::HexDigest(digest.finalize())
        ),
        entity: op.entity.clone(),
        client_key,
    };
    key.visit_identity_bytes(|_| ())
        .map_err(|_| super::denied())?;
    Ok(key)
}
impl StateRuntime {
    pub(super) fn original_operation(
        &self,
        current: &InstalledTransactionOperation,
        record: &CommandRecord,
    ) -> Result<Arc<InstalledTransactionOperation>, PlatformError> {
        let source = record.source();
        let op = self
            .0
            .installed
            .iter()
            .find(|op| {
                op.publication.publication().as_str() == source.publication
                    && op.publication.release().0 == source.component_digest
                    && op.contract_digest == source.contract_digest
                    && op.target.tenant == current.target.tenant
                    && op.target.service == current.target.service
                    && op.target.contract == current.target.contract
                    && op.target.function == current.target.function
                    && op.binding() == current.binding()
                    && op.namespace() == current.namespace()
                    && op.incarnation == current.incarnation
                    && op.entity == current.entity
                    && op.state_schema() == current.state_schema()
                    && op.result_policy == record.result_read_policy()
                    && op.mode == latent_manifest::TransactionOperationMode::StrictCommand
                    && source.input_format == "lsf-wit-values-v1"
                    && source.result_format == "lsf-wit-values-v1"
            })
            .ok_or_else(super::denied)?;
        op.publication.check_current()?;
        Ok(Arc::clone(op))
    }
}
