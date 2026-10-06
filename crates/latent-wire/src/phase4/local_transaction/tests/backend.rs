//! Observe actual compiled-guest imports, preserving the real backend/control.
use super::*;
use latent_artifacts::{ArtifactRepository, CapsuleArtifact};
use latent_core::{ActivationBudget, ActivationId, EffectiveDeadline, ReleaseDigest};
use latent_executor::transaction::*;
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionCancellationProbe, ExecutionReport,
    ExecutionRequest, GuestOutcome, PreparationKey, PreparationReadWait, PreparedActivation,
    PreparedComponent, PreparedReadiness, PreparedUse,
};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use tokio::sync::Notify;

#[derive(Default)]
pub(super) struct Imports {
    pub commands: AtomicU64,
    pub queries: AtomicU64,
    pub pause_read: AtomicBool,
    pub entered: Notify,
    pub release: Notify,
}

struct Host {
    inner: Arc<dyn TransactionHost>,
    imports: Arc<Imports>,
}
impl TransactionHost for Host {
    fn activation_id(&self) -> &ActivationId {
        self.inner.activation_id()
    }
    fn mode(&self) -> Mode {
        self.inner.mode()
    }
    fn budget(&self) -> &ActivationBudget {
        self.inner.budget()
    }
    fn acquire(&self, mode: Mode) -> Result<(), StateFailure> {
        self.inner.acquire(mode)?;
        match mode {
            Mode::Command => &self.imports.commands,
            Mode::Query => &self.imports.queries,
        }
        .fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
    fn release(&self, mode: Mode) {
        self.inner.release(mode);
    }
    fn view_identity(&self) -> Result<ViewIdentity, StateFailure> {
        self.inner.view_identity()
    }
    fn command_info(&self) -> Result<CommandInfo, StateFailure> {
        self.inner.command_info()
    }
    fn authorize_read(&self) -> Result<(), StateFailure> {
        self.inner.authorize_read()
    }
    fn retain_transfer(&self, bytes: usize) -> Result<RetainedTransfer, StateFailure> {
        self.inner.retain_transfer(bytes)
    }
    fn read(&self, key: Vec<u8>) -> BoxFuture<'_, Result<Option<VersionedValue>, StateFailure>> {
        Box::pin(async move {
            if self.mode() == Mode::Command && self.imports.pause_read.swap(false, Ordering::SeqCst)
            {
                self.imports.entered.notify_one();
                let deadline = self
                    .budget()
                    .deadline()
                    .monotonic()
                    .ok_or(StateFailure::Cancelled)?;
                tokio::select! {
                    () = self.imports.release.notified() => {},
                    () = tokio::time::sleep_until(deadline.into()) => return Err(StateFailure::Cancelled),
                }
            }
            self.inner.read(key).await
        })
    }
    fn scan(
        &self,
        prefix: Vec<u8>,
        limit: u32,
        cursor: Option<Vec<u8>>,
    ) -> BoxFuture<'_, Result<Page, StateFailure>> {
        self.inner.scan(prefix, limit, cursor)
    }
    fn put(
        &self,
        key: Vec<u8>,
        value: latent_core::transaction_contract::Value,
    ) -> BoxFuture<'_, Result<(), StateFailure>> {
        self.inner.put(key, value)
    }
    fn delete(&self, key: Vec<u8>) -> BoxFuture<'_, Result<(), StateFailure>> {
        self.inner.delete(key)
    }
    fn stage(&self, intent: Intent) -> BoxFuture<'_, Result<u32, IntentFailure>> {
        self.inner.stage(intent)
    }
    fn finish_guest_access(&self) {
        self.inner.finish_guest_access();
    }
}

struct Control<'a> {
    inner: &'a dyn ExecutionCancellation,
    host: Arc<dyn TransactionHost>,
}
impl ExecutionCancellation for Control<'_> {
    fn activation_id(&self) -> &ActivationId {
        self.inner.activation_id()
    }
    fn is_cancelled(&self) -> bool {
        self.inner.is_cancelled()
    }
    fn reason(&self) -> Option<String> {
        self.inner.reason()
    }
    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        self.inner.probe()
    }
    fn effective_deadline(&self) -> Option<&EffectiveDeadline> {
        self.inner.effective_deadline()
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        self.inner.budget_accounting()
    }
    fn transaction_host(&self) -> Option<Arc<dyn TransactionHost>> {
        Some(Arc::clone(&self.host))
    }
}

pub(super) struct Backend {
    pub real: Arc<latent_wasmtime::WasmtimeBackend>,
    pub imports: Arc<Imports>,
}
impl ExecutionBackend for Backend {
    fn backend_id(&self) -> &str {
        self.real.backend_id()
    }
    fn preparation_key(&self, release: &ReleaseDigest) -> Result<PreparationKey, PlatformError> {
        self.real.preparation_key(release)
    }
    fn prepare_ready_from_repository_with_wait<'a>(
        &'a self,
        repository: Arc<dyn ArtifactRepository>,
        key: PreparationKey,
        wait: &'a dyn PreparationReadWait,
    ) -> BoxFuture<'a, Result<PreparedReadiness, PlatformError>> {
        self.real
            .prepare_ready_from_repository_with_wait(repository, key, wait)
    }
    fn materialize_ready_with_wait<'a>(
        &'a self,
        ready: PreparedReadiness,
        wait: &'a dyn PreparationReadWait,
    ) -> BoxFuture<'a, Result<PreparedActivation, PlatformError>> {
        self.real.materialize_ready_with_wait(ready, wait)
    }
    fn invoke_prepared_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        prepared: PreparedUse,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let inner = cancellation
                .transaction_host()
                .expect("production transaction host");
            let control = Control {
                inner: cancellation,
                host: Arc::new(Host {
                    inner,
                    imports: Arc::clone(&self.imports),
                }),
            };
            self.real
                .invoke_prepared_contained(request, prepared, &control)
                .await
        })
    }
    fn prepare<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        self.real.prepare(artifact, key)
    }
    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        self.real.invoke(request, cancellation)
    }
    fn release(&self, prepared: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.real.release(prepared)
    }
}
