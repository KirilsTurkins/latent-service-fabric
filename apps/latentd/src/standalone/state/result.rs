use super::{role::AdmissionTime, InstalledTransactionOperation, StateRuntime};
use latent_activation::ActivationEnvelope;
use latent_core::{ActivationBudget, BoxFuture, PlatformError};
use latent_node::{
    transaction_runtime::{command_completion::CommandResultCodec, CommandTimeSource},
    TransactionActivationAdmission, TransactionAdmission, TransactionAdmissionControl,
    TransactionAdmissionKind,
};
use latent_state::store_io::StoreIoKind;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};

pub(super) struct ResultAdmission {
    runtime: StateRuntime,
    installed: Arc<InstalledTransactionOperation>,
    original_id: String,
    codec: Arc<dyn CommandResultCodec>,
    time: Arc<AdmissionTime>,
    control: Mutex<Option<TransactionAdmissionControl>>,
    admitted: AtomicBool,
}
impl ResultAdmission {
    pub fn new(
        runtime: StateRuntime,
        installed: Arc<InstalledTransactionOperation>,
        original_id: String,
        codec: Arc<dyn CommandResultCodec>,
    ) -> Self {
        let time = AdmissionTime::new(runtime.0.source.clone(), runtime.0.native.clone());
        Self {
            runtime,
            installed,
            original_id,
            codec,
            time,
            control: Mutex::new(None),
            admitted: AtomicBool::new(false),
        }
    }
    async fn existing(
        &self,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<TransactionAdmission, PlatformError> {
        if self.admitted.swap(true, Ordering::AcqRel) {
            return Err(super::denied());
        }
        let control = self
            .control
            .lock()
            .map_err(|_| super::denied())?
            .take()
            .ok_or_else(super::denied)?;
        self.runtime.accepts(&self.installed, envelope, budget)?;
        let granted = budget.granted();
        if granted.state_write_bytes != 0
            || granted.effect_count != 0
            || granted.child_calls != 0
            || granted.outbound_requests != 0
        {
            return Err(super::denied());
        }
        self.time.retain_admission(envelope, budget)?;
        let decision = self
            .runtime
            .retain(&self.installed, envelope, budget, "read-result")?;
        let (_, namespace) = self
            .runtime
            .namespaces(
                &self.installed,
                budget,
                self.time.clone(),
                StoreIoKind::RecoveryRead,
            )
            .await?;
        let current_read =
            self.runtime
                .seal(&self.installed, envelope, budget, namespace, decision)?;
        let key = super::command::command_key(&self.installed, envelope, self.original_id.clone())?;
        let coordinator = self.runtime.coordinator(self.time.clone());
        let mut original = coordinator
            .original_metadata(key.clone(), current_read)
            .await?
            .ok_or_else(super::unavailable)?;
        let op = self
            .runtime
            .original_operation(&self.installed, original.original_command())?;
        let decision = self.runtime.retain(&op, envelope, budget, "read-result")?;
        let read =
            self.runtime
                .seal(&op, envelope, budget, original.take_namespace()?, decision)?;
        control.bind_result(&read)?;
        let completion = coordinator
            .lookup(key, read, Arc::clone(&self.codec), false, None)
            .await;
        Ok(TransactionAdmission::Existing(Box::new(completion)))
    }
}
impl TransactionActivationAdmission for ResultAdmission {
    fn kind(&self) -> TransactionAdmissionKind {
        TransactionAdmissionKind::ResultLookup
    }
    fn bind_control(&self, control: TransactionAdmissionControl) -> Result<(), PlatformError> {
        let mut slot = self.control.lock().map_err(|_| super::denied())?;
        if slot.is_some() || self.admitted.load(Ordering::Acquire) {
            return Err(super::denied());
        }
        *slot = Some(control);
        Ok(())
    }
    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<TransactionAdmission, PlatformError>> {
        Box::pin(self.existing(envelope, budget))
    }
}
