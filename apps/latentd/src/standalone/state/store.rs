//! Original protected initialization; callers never receive an unbound engine.
use std::sync::Arc;

use latent_core::{native_capacity::NativeCapacityOwner, PlatformError};
use latent_state::embedded::StoreError;
use latent_state::protected_store::{ProtectedStoreOwner, ProtectedStoreStartup};

use super::{bootstrap::StateBootstrap, validation};
use crate::config::state::{StateSettings, STARTUP_VALIDATOR_BYTES};
use crate::standalone::startup_observation::{record, record_platform, Stage};

/// Observe the original worker handles until they actually exit, without
/// extending the caller's existing shutdown cutoff.
pub(super) async fn join_retired_workers(
    store: &ProtectedStoreOwner,
    deadline: std::time::Instant,
) -> Result<Option<usize>, latent_state::protected_store::ProtectedStoreError> {
    let mut joined = 0;
    loop {
        if std::time::Instant::now() >= deadline {
            return Ok(None);
        }
        joined += store.reap_retired_threads()?;
        if store.pending_thread_joins()? == 0 {
            return Ok((std::time::Instant::now() < deadline).then_some(joined));
        }
        let now = std::time::Instant::now();
        if now >= deadline {
            return Ok(None);
        }
        tokio::time::sleep_until(
            (now + std::time::Duration::from_millis(1))
                .min(deadline)
                .into(),
        )
        .await;
    }
}

/// This guard is private to one startup future. Losing that future closes the
/// original global owner and quarantines accepted native initialization, while
/// the lower fixed worker continues to own its actual descriptors and buffers.
struct StartingStore {
    startup: ProtectedStoreStartup,
    native: NativeCapacityOwner,
    delivered: bool,
}

#[cfg(target_os = "linux")]
struct StartingPayloadPromotion {
    store: Arc<ProtectedStoreOwner>,
    native: NativeCapacityOwner,
    delivered: bool,
}

#[cfg(target_os = "linux")]
impl Drop for StartingPayloadPromotion {
    fn drop(&mut self) {
        if !self.delivered {
            self.store.quarantine();
            self.native.quarantine();
        }
    }
}

enum StartupPayload {
    None,
    #[cfg(target_os = "linux")]
    Local {
        owner: Arc<latent_blobs::local::LocalBlobStore>,
        provider: crate::config::ProviderIdentity,
        returned: std::sync::mpsc::SyncSender<(Arc<latent_blobs::local::LocalBlobStore>, bool)>,
    },
}

#[cfg(target_os = "linux")]
pub(super) struct LocalPayloadSelection {
    provider: crate::config::ProviderIdentity,
    namespace: String,
    root: std::path::PathBuf,
    durable_retention: bool,
}

#[cfg(target_os = "linux")]
impl LocalPayloadSelection {
    pub(super) fn matches(
        &self,
        settings: &crate::config::NodeSettings,
        blob: &crate::config::BlobInstallation,
    ) -> bool {
        self.provider.id == blob.identity.id
            && self.provider.tenant == blob.identity.tenant
            && self.provider.service == blob.identity.service
            && self.provider.epoch == blob.identity.epoch
            && self.namespace == blob.namespace
            && self.durable_retention == blob.durable_retention
            && self.root
                == settings
                    .data_directory
                    .join(format!("provider-blobs-{}", blob.identity.id))
    }
}

impl Drop for StartingStore {
    fn drop(&mut self) {
        if !self.delivered {
            self.startup.quarantine();
            self.native.quarantine();
        }
    }
}

fn validate_startup_payload(
    view: &latent_state::embedded::ReadView,
    identity: &latent_state::store_identity::StoreIdentity,
    quotas: &[latent_state::tenant::TenantQuota],
    original: &latent_core::native_capacity::NativeReservation,
    payload: StartupPayload,
) -> Result<(), StoreError> {
    match payload {
        StartupPayload::None => validation::validate(view, identity, quotas, original),
        #[cfg(target_os = "linux")]
        StartupPayload::Local {
            mut owner,
            provider,
            returned,
        } => {
            let durable = latent_blobs::local::LocalBlobStore::bind_existing_durable_for_view(
                &mut owner, view,
            )
            .map_err(|_| StoreError::Unavailable)?;
            if durable {
                validation::validate_with_local_payloads(
                    view,
                    identity,
                    quotas,
                    original,
                    &validation::LocalPayloadVerifier {
                        store: &owner,
                        provider: &provider,
                        original,
                    },
                )?;
            } else {
                validation::validate(view, identity, quotas, original)?;
            }
            validation::live(original)?;
            returned
                .send((owner, durable))
                .map_err(|_| StoreError::Unavailable)
        }
    }
}

impl StateBootstrap {
    /// Prepaid initialization runs on the same fixed node storage workers used
    /// by commands and recovery. The exact initial identity transaction is the
    /// only producer of Fresh checkpoint evidence, never matching config bytes.
    pub(super) async fn open_store(
        &mut self,
        settings: &StateSettings,
    ) -> Result<Arc<ProtectedStoreOwner>, PlatformError> {
        self.open_store_inner(settings, None, false, StartupPayload::None)
            .await
    }

    pub(in crate::standalone::state) async fn open_store_offline(
        &mut self,
        settings: &StateSettings,
    ) -> Result<Arc<ProtectedStoreOwner>, PlatformError> {
        self.open_store_inner(settings, None, true, StartupPayload::None)
            .await
    }

    /// Transfer the unique already-open provider owner into the initializing
    /// worker. A timeout never returns that owner while physical work survives.
    #[cfg(target_os = "linux")]
    pub(in crate::standalone) async fn open_store_with_local_payloads(
        &mut self,
        settings: &StateSettings,
        owner: Arc<latent_blobs::local::LocalBlobStore>,
        provider: crate::config::ProviderIdentity,
        root: std::path::PathBuf,
        durable_retention: bool,
    ) -> Result<Arc<latent_blobs::local::LocalBlobStore>, PlatformError> {
        self.open_store_with_local_payloads_inner(
            settings,
            owner,
            provider,
            root,
            durable_retention,
            None,
        )
        .await
    }

    #[cfg(target_os = "linux")]
    async fn open_store_with_local_payloads_inner(
        &mut self,
        settings: &StateSettings,
        owner: Arc<latent_blobs::local::LocalBlobStore>,
        provider: crate::config::ProviderIdentity,
        root: std::path::PathBuf,
        durable_retention: bool,
        before_promotion: Option<Box<dyn FnOnce() + Send>>,
    ) -> Result<Arc<latent_blobs::local::LocalBlobStore>, PlatformError> {
        let selection = LocalPayloadSelection {
            provider: provider.clone(),
            namespace: owner.namespace().to_owned(),
            root,
            durable_retention,
        };
        let (returned, receiver) = std::sync::mpsc::sync_channel(1);
        let store = self
            .open_store_inner(
                settings,
                None,
                false,
                StartupPayload::Local {
                    owner,
                    provider,
                    returned,
                },
            )
            .await?;
        self.check_live()?;
        let (mut owner, already_durable) = receiver.try_recv().map_err(|_| super::unavailable())?;
        if durable_retention && !already_durable {
            use latent_state::store_io::StoreIoKind;
            // A dropped startup waiter cannot expose the store while the
            // accepted physical mode transition is still running.
            let mut guard = StartingPayloadPromotion {
                store: Arc::clone(&store),
                native: self.native.clone(),
                delivered: false,
            };
            let original = self.original();
            let current = Arc::clone(&original);
            let job = store
                .with_store_retaining(StoreIoKind::RecoveryWrite, 4096, original, move |engine| {
                    validation::live(&current)?;
                    if let Some(observe) = before_promotion {
                        observe();
                    }
                    validation::live(&current)?;
                    let view = engine.snapshot()?;
                    let result = latent_blobs::local::LocalBlobStore::enable_durable_for_view(
                        &mut owner, &view,
                    );
                    validation::live(&current)?;
                    Ok((owner, result))
                })
                .map_err(|_| super::unavailable())?;
            owner = if let Ok(Ok(Ok((owner, Ok(()))))) =
                tokio::time::timeout_at(self.deadline.into(), job).await
            {
                owner
            } else {
                return Err(super::unavailable());
            };
            self.check_live()?;
            guard.delivered = true;
        }
        self.local_payload_selection = Some(Box::new(selection));
        Ok(owner)
    }

    async fn open_store_inner(
        &mut self,
        settings: &StateSettings,
        before_validation: Option<Box<dyn FnOnce() + Send>>,
        offline: bool,
        payload: StartupPayload,
    ) -> Result<Arc<ProtectedStoreOwner>, PlatformError> {
        self.check_live()?;
        if self.opened_store.is_some() || !self.matches(settings) {
            return Err(super::unavailable());
        }
        let original = self.original();
        let identity = settings.store_identity.clone();
        let quotas = validation::quotas(settings);
        let mut configuration = settings.store.clone();
        if offline {
            configuration.create_if_missing = false;
        }
        let initializer = ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
            configuration,
            identity.clone(),
            self.take_memory()?,
            STARTUP_VALIDATOR_BYTES,
            move |view| {
                if offline
                    && (latent_state::store_identity::StoreIdentity::inspect(view)?.as_ref()
                        != Some(&identity)
                        || latent_state::tenant::require_installation(view, &quotas).is_err())
                {
                    return Err(StoreError::UnsupportedFormat);
                }
                if let Some(observe) = before_validation {
                    observe();
                }
                validate_startup_payload(view, &identity, &quotas, &original, payload)
            },
            Arc::clone(&self.clock),
        )
        .inspect_err(|error| record(Stage::ProtectedStoreInitializerAdmission, *error))
        .map_err(|_| super::unavailable())?;
        let mut guard = StartingStore {
            startup: initializer,
            native: self.native.clone(),
            delivered: false,
        };
        let result = tokio::time::timeout_at(self.deadline.into(), &mut guard.startup).await;
        if let Ok(Err(error)) = &result {
            record(Stage::ProtectedStoreInitializerCompletion, *error);
        }
        let deadline_elapsed = result.is_err();
        let store = if let Ok(Ok(store)) = result {
            Arc::new(store)
        } else {
            // Observation timeout is never abort or physical retirement.
            // The original absolute cutoff remains unchanged for cleanup;
            // accepted work keeps its original memory if it cannot finish.
            guard.startup.quarantine();
            if let Ok(drain) = guard.startup.drain_async(
                self.deadline,
                tokio::time::sleep_until(self.deadline.into()),
            ) {
                let _report = drain.await;
            }
            let failure = super::unavailable();
            if deadline_elapsed {
                record_platform(Stage::ProtectedStoreInitializerDeadline, &failure);
            }
            return Err(failure);
        };
        if !store.uses_native_capacity(&self.native) || self.check_live().is_err() {
            store.quarantine();
            self.native.quarantine();
            if let Ok(drain) = store.drain_async(
                self.deadline,
                tokio::time::sleep_until(self.deadline.into()),
            ) {
                let _report = drain.await;
            }
            return Err(super::unavailable());
        }
        // Keep the actual owner in the original boot lifetime until the final
        // standalone runtime has installed current permissions and readiness.
        self.opened_store = Some(Arc::clone(&store));
        guard.delivered = true;
        Ok(store)
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;
