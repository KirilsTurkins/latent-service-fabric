//! One lifecycle owner from accepted identity through terminal publication.

mod control;
mod lifecycle;
mod run;

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Duration;

use latent_activation::{
    ActivationEnvelope, ActivationEvent, ActivationIdSource, ActivationManager, ActivationOutcome,
    ActivationRequest, ActivationRequestBuilder, ActivationRequestLimits, ActivationStatus,
    SystemActivationIdSource,
};
use latent_admission::LocalAdmissionController;
use latent_artifacts::ArtifactRepository;
use latent_core::{
    ActivationClock, ActivationId, BoxFuture, BudgetConsumption, CancelDisposition, PlatformError,
    PlatformErrorCode, SystemActivationClock, TenantId,
};
use latent_executor::ExecutionBackend;
use latent_routing::{ActivationCatalogSource, ResolvedRevision};
use latent_scheduler::ActivationScheduler;

use crate::activation_runner::failure_for_platform_error;
use crate::{
    ActivationCancellationRegistry, CancellationRegistrySnapshot, LocalActivationJournal,
    LocalActivationJournalConfig,
};
use control::{error, CatchPanic};
use lifecycle::Lifecycle;

#[derive(Debug, Clone)]
pub struct LocalActivationManagerConfig {
    pub requests: ActivationRequestLimits,
    pub journal: LocalActivationJournalConfig,
    pub maximum_cancellation_reason_bytes: usize,
    /// Bound cooperative backend/pool cleanup after cancellation or expiry.
    pub cleanup_grace: Duration,
}

impl Default for LocalActivationManagerConfig {
    fn default() -> Self {
        Self {
            requests: ActivationRequestLimits::default(),
            journal: LocalActivationJournalConfig::default(),
            maximum_cancellation_reason_bytes: 256,
            cleanup_grace: Duration::from_millis(100),
        }
    }
}

#[derive(Clone)]
pub struct LocalActivationDependencies {
    pub catalog: Arc<dyn ActivationCatalogSource>,
    pub admission: LocalAdmissionController,
    pub scheduler: Arc<dyn ActivationScheduler>,
    pub artifacts: Arc<dyn ArtifactRepository>,
    pub backend: Arc<dyn ExecutionBackend>,
}

#[derive(Clone)]
pub struct LocalActivationServices {
    pub clock: Arc<dyn ActivationClock>,
    pub ids: Arc<dyn ActivationIdSource>,
}

impl Default for LocalActivationServices {
    fn default() -> Self {
        Self {
            clock: Arc::new(SystemActivationClock),
            ids: Arc::new(SystemActivationIdSource::default()),
        }
    }
}

/// Complete response identity is separate from the outcome and retained status.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationReceipt {
    pub activation_id: ActivationId,
    pub resolved_revision: Option<ResolvedRevision>,
    pub outcome: ActivationOutcome,
}

/// No detached task is spawned. Dropping this handle, even before its first
/// poll, completes its accepted journal entry through the same lifecycle guard.
#[must_use = "await the activation, or drop it to abandon and reclaim its work"]
pub struct ActivationHandle {
    activation_id: ActivationId,
    completion: Pin<Box<dyn Future<Output = ActivationReceipt> + Send>>,
}

impl ActivationHandle {
    #[must_use]
    pub fn activation_id(&self) -> &ActivationId {
        &self.activation_id
    }
}

impl Future for ActivationHandle {
    type Output = ActivationReceipt;
    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        self.completion.as_mut().poll(context)
    }
}

struct Inner {
    config: LocalActivationManagerConfig,
    dependencies: LocalActivationDependencies,
    clock: Arc<dyn ActivationClock>,
    requests: ActivationRequestBuilder,
    journal: LocalActivationJournal,
    cancellations: ActivationCancellationRegistry,
}

#[derive(Clone)]
pub struct LocalActivationManager {
    inner: Arc<Inner>,
}

impl LocalActivationManager {
    pub fn new(
        config: LocalActivationManagerConfig,
        dependencies: LocalActivationDependencies,
    ) -> Result<Self, PlatformError> {
        Self::with_services(config, dependencies, LocalActivationServices::default())
    }

    pub fn with_services(
        config: LocalActivationManagerConfig,
        dependencies: LocalActivationDependencies,
        services: LocalActivationServices,
    ) -> Result<Self, PlatformError> {
        if config.cleanup_grace.is_zero() || config.cleanup_grace > Duration::from_secs(1) {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid activation cleanup grace",
            ));
        }
        let requests = ActivationRequestBuilder::new(config.requests, services.ids)?;
        let journal = LocalActivationJournal::new(config.journal, Arc::clone(&services.clock))?;
        let cancellations =
            ActivationCancellationRegistry::new(config.maximum_cancellation_reason_bytes)?;
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                dependencies,
                clock: services.clock,
                requests,
                journal,
                cancellations,
            }),
        })
    }

    /// Authenticate before calling this method. Context and lineage fields never
    /// replace the principal/target tenant check performed by the request builder.
    pub fn start(&self, request: ActivationRequest) -> Result<ActivationHandle, PlatformError> {
        let envelope = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            self.inner.requests.build(request)
        }))
        .map_err(|_| {
            error(
                PlatformErrorCode::Internal,
                "activation request builder panicked",
            )
        })??;
        let activation_id = envelope.activation_id.clone();
        let (journal, cancellation) = self.inner.journal.begin_with(&envelope, || {
            self.inner.cancellations.register(activation_id.clone())
        })?;
        let lifecycle = Lifecycle::new(journal, cancellation, Arc::clone(&self.inner.clock));
        let inner = Arc::clone(&self.inner);
        let completion = Box::pin(async move {
            let mut lifecycle = lifecycle;
            let result = CatchPanic::new(inner.drive(envelope, &mut lifecycle)).await;
            let outcome = match result {
                Ok(outcome) => outcome,
                Err(()) => failure_for_platform_error(
                    error(
                        PlatformErrorCode::Internal,
                        "activation execution or cleanup panicked",
                    ),
                    BudgetConsumption::default(),
                ),
            };
            let resolved_revision = lifecycle.resolved.clone();
            let activation_id = lifecycle.activation_id().clone();
            let outcome = lifecycle.complete(outcome);
            ActivationReceipt {
                activation_id,
                resolved_revision,
                outcome,
            }
        });
        Ok(ActivationHandle {
            activation_id,
            completion,
        })
    }

    pub fn status(
        &self,
        tenant: &TenantId,
        id: &ActivationId,
    ) -> Result<Option<ActivationStatus>, PlatformError> {
        self.validate_query_size(tenant, id)?;
        self.inner.journal.status(tenant, id)
    }

    pub fn events(
        &self,
        tenant: &TenantId,
        id: &ActivationId,
    ) -> Result<Vec<ActivationEvent>, PlatformError> {
        self.validate_query_size(tenant, id)?;
        self.inner.journal.events(tenant, id)
    }

    /// Authorization and cancellation share the journal's identity lock, so
    /// eviction and ID reuse cannot redirect a tenant's cancellation request.
    pub fn cancel_for(
        &self,
        tenant: &TenantId,
        id: &ActivationId,
        reason: &str,
    ) -> Result<CancelDisposition, PlatformError> {
        self.validate_query_size(tenant, id)?;
        self.inner
            .journal
            .cancel_with(tenant, id, || self.inner.cancellations.cancel(id, reason))
    }

    fn validate_query_size(
        &self,
        tenant: &TenantId,
        id: &ActivationId,
    ) -> Result<(), PlatformError> {
        let maximum = self.inner.config.requests.maximum_identifier_bytes;
        if tenant.0.len() > maximum || id.0.len() > maximum {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "activation query identifier exceeds its bound",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn journal(&self) -> LocalActivationJournal {
        self.inner.journal.clone()
    }
    #[must_use]
    pub fn cancellation_snapshot(&self) -> CancellationRegistrySnapshot {
        self.inner.cancellations.snapshot()
    }
}

impl ActivationManager for LocalActivationManager {
    fn invoke(&self, envelope: ActivationEnvelope) -> BoxFuture<'_, ActivationOutcome> {
        // A caller-provided revision is not a trusted catalog view.
        let started = self.start(ActivationRequest::from_envelope(envelope));
        Box::pin(async move {
            match started {
                Ok(handle) => handle.await.outcome,
                Err(error) => failure_for_platform_error(error, BudgetConsumption::default()),
            }
        })
    }

    fn cancel<'a>(
        &'a self,
        _id: &'a ActivationId,
        _reason: &'a str,
    ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>> {
        // This old port carries no authenticated tenant. Product adapters must
        // use cancel_for rather than turning knowledge of an ID into authority.
        Box::pin(async {
            Err(error(
                PlatformErrorCode::PermissionDenied,
                "activation cancellation requires tenant scope",
            ))
        })
    }
}
