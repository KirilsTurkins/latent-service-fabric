use super::{OfflineRecoveryError, OfflineRecoverySource, RecoveryCodecs, CODEC_BYTES};
use crate::{
    namespace::compatibility::RetainedInventory,
    protected_store::{
        ProtectedStoreConfig, ProtectedStoreDrain, ProtectedStoreError, ProtectedStoreOwner,
        ProtectedStoreStartup,
    },
    store_io::StoreIoSnapshot,
};
use std::{
    future::Future,
    path::PathBuf,
    pin::Pin,
    sync::{atomic::AtomicBool, Arc},
    task::{Context, Poll},
    time::Instant,
};

#[must_use = "readiness requires actual exclusive offline source ownership"]
pub struct OfflineRecoveryStartup {
    inner: ProtectedStoreStartup,
    codecs: Arc<dyn RecoveryCodecs>,
    source_root: PathBuf,
    tenant: String,
}

impl OfflineRecoverySource {
    pub fn start(
        config: ProtectedStoreConfig,
        tenant: String,
        codecs: Arc<dyn RecoveryCodecs>,
    ) -> Result<OfflineRecoveryStartup, OfflineRecoveryError> {
        Self::start_mode(config, tenant, codecs, false)
    }

    /// Deliberate administrative opening of paused restored history. Actual
    /// exclusive root ownership still retires every normal physical owner.
    /// This exposes only installed review ports, never ordinary business work.
    /// Incomplete staged restore remains refused and requires recovery.
    pub fn start_review(
        config: ProtectedStoreConfig,
        tenant: String,
        codecs: Arc<dyn RecoveryCodecs>,
    ) -> Result<OfflineRecoveryStartup, OfflineRecoveryError> {
        Self::start_mode(config, tenant, codecs, true)
    }

    fn start_mode(
        mut config: ProtectedStoreConfig,
        tenant: String,
        codecs: Arc<dyn RecoveryCodecs>,
        review: bool,
    ) -> Result<OfflineRecoveryStartup, OfflineRecoveryError> {
        crate::namespace::identity(&tenant)
            .map_err(|_| OfflineRecoveryError::InvalidConfiguration)?;
        if config.create_if_missing
            || codecs.runtime_digest() == [0; 32]
            || codecs.retained_bytes() > CODEC_BYTES
            || codecs.scratch_bytes() > CODEC_BYTES
        {
            return Err(OfflineRecoveryError::InvalidConfiguration);
        }
        RetainedInventory::default()
            .require_decoders(codecs.installed_formats())
            .map_err(|_| OfflineRecoveryError::InvalidConfiguration)?;
        config.io.resident_bytes = config
            .io
            .resident_bytes
            .checked_add(codecs.retained_bytes())
            .ok_or(OfflineRecoveryError::InvalidConfiguration)?;
        let validator = Arc::clone(&codecs);
        let validation_tenant = tenant.clone();
        let source_root = config.root.clone();
        let inner = ProtectedStoreOwner::start_validated_view(
            config,
            codecs.scratch_bytes(),
            move |view| {
                if review {
                    if super::super::RecoveryGuard::capture(view)?.is_some_and(|guard| {
                        guard.status() == super::super::RecoveryStatus::Staging
                    }) {
                        return Err(crate::embedded::StoreError::Unavailable);
                    }
                    super::super::snapshot::capture_namespaces_for_review(
                        view,
                        &validation_tenant,
                    )?;
                } else {
                    super::super::require_ready(view)?;
                    super::super::snapshot::capture_namespaces(view, &validation_tenant)?;
                }
                validator
                    .validate_view(view)?
                    .inventory
                    .require_decoders(validator.installed_formats())
                    .map_err(|_| crate::embedded::StoreError::UnsupportedFormat)?;
                Ok(())
            },
        )
        .map_err(OfflineRecoveryError::Protected)?;
        Ok(OfflineRecoveryStartup {
            inner,
            codecs,
            source_root,
            tenant,
        })
    }
}

impl OfflineRecoveryStartup {
    pub fn snapshot(&self) -> Result<StoreIoSnapshot, ProtectedStoreError> {
        self.inner.snapshot()
    }
    pub fn close(&self) {
        self.inner.close();
    }
    pub fn drain_async<F: Future<Output = ()>>(
        &self,
        deadline: Instant,
        wait: F,
    ) -> Result<ProtectedStoreDrain<F>, ProtectedStoreError> {
        self.inner.drain_async(deadline, wait)
    }
}

impl Future for OfflineRecoveryStartup {
    type Output = Result<OfflineRecoverySource, OfflineRecoveryError>;
    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        match Pin::new(&mut this.inner).poll(context) {
            Poll::Ready(Ok(owner)) => Poll::Ready(Ok(OfflineRecoverySource {
                owner,
                codecs: Arc::clone(&this.codecs),
                source_root: this.source_root.clone(),
                tenant: this.tenant.clone(),
                busy: Arc::new(AtomicBool::new(false)),
            })),
            Poll::Ready(Err(error)) => Poll::Ready(Err(OfflineRecoveryError::Protected(error))),
            Poll::Pending => Poll::Pending,
        }
    }
}
