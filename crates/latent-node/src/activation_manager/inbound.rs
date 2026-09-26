//! A trusted inbound adapter reserves node admission before receiving a payload.
use super::{
    control::{cancelled, deadline_error, error},
    failure_for_platform_error, handle, ActivationEnvelope, ActivationHandle, ActivationRequest,
    BudgetConsumption, IncomingDeadline, Inner, Lifecycle, LocalActivationManager, PlatformError,
    PlatformErrorCode, ResolvedRevision, TransportStop,
};
use latent_artifacts::ReleaseUseEligibility;
use latent_core::ActivationId;
use std::{sync::Arc, time::Instant};

/// Owns one pinned admission and its maximum input allocation before a pull.
/// No backend preparation, execution cell or task exists until `start` is polled.
/// Dropping an empty/abandoned pull releases its reservation without executing.
#[must_use = "retain until the delivery starts or the pull is abandoned"]
pub struct InboundActivationReservation {
    // Destroy payload bytes before returning the lifecycle's quota reservation.
    envelope: ActivationEnvelope,
    lifecycle: Lifecycle,
    manager: Arc<Inner>,
}

impl LocalActivationManager {
    /// Authenticate/configure the principal and target before calling. The
    /// input must be empty; this method allocates only after reserving admission
    /// for the trusted maximum. Network headers never supply authority/lineage.
    pub fn reserve_inbound(
        &self,
        request: ActivationRequest,
        maximum_input_bytes: usize,
        deadline: IncomingDeadline,
    ) -> Result<InboundActivationReservation, PlatformError> {
        self.reserve_inbound_inner(request, maximum_input_bytes, deadline, None)
    }

    /// Trusted node adapter entry point for an already selected trigger. Preserve
    /// the exact revision and immutable policy view across concurrent cutovers.
    /// This is not a wire-supplied pin or an admission bypass: the catalog must
    /// validate the complete tuple, including current publication authority.
    pub fn reserve_selected_inbound(
        &self,
        request: ActivationRequest,
        maximum_input_bytes: usize,
        deadline: IncomingDeadline,
        revision: ResolvedRevision,
        catalog: Arc<dyn latent_routing::ActivationCatalog>,
    ) -> Result<InboundActivationReservation, PlatformError> {
        self.reserve_inbound_inner(
            request,
            maximum_input_bytes,
            deadline,
            Some((revision, catalog)),
        )
    }

    fn reserve_inbound_inner(
        &self,
        request: ActivationRequest,
        maximum_input_bytes: usize,
        deadline: IncomingDeadline,
        selected: Option<(ResolvedRevision, Arc<dyn latent_routing::ActivationCatalog>)>,
    ) -> Result<InboundActivationReservation, PlatformError> {
        if request.input.capacity() != 0
            || maximum_input_bytes == 0
            || maximum_input_bytes > self.inner.config.requests.maximum_input_bytes
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid inbound input reservation",
            ));
        }
        if deadline.monotonic() <= self.inner.clock.monotonic_now() {
            return Err(deadline_error());
        }
        let mut envelope = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            self.inner.requests.build(request)
        }))
        .map_err(|_| {
            error(
                PlatformErrorCode::Internal,
                "inbound request builder panicked",
            )
        })??;
        let (journal, cancellation) = self.inner.journal.begin_with(&envelope, || {
            self.inner
                .cancellations
                .register(envelope.activation_id.clone())
        })?;
        let mut lifecycle = Lifecycle::new(
            journal,
            cancellation,
            self.inner.clock.clone(),
            Arc::new(TransportStop::default()),
            Some(deadline),
        );
        lifecycle.begin_observation(self.inner.observations.as_ref(), &envelope);
        let token = lifecycle.registration().token();
        let admitted = (|| {
            let (permit, _) = self.inner.resolve_and_admit_input(
                &mut envelope,
                &mut lifecycle,
                &token,
                None,
                Some(maximum_input_bytes),
                selected,
            )?;
            lifecycle.inbound_permit = Some(permit);
            envelope
                .input
                .try_reserve_exact(maximum_input_bytes)
                .map_err(|_| {
                    error(
                        PlatformErrorCode::ResourceExhausted,
                        "inbound input allocation unavailable",
                    )
                })?;
            envelope.input.resize(maximum_input_bytes, 0);
            Ok::<_, PlatformError>(())
        })();
        if let Err(failure) = admitted {
            drop(envelope);
            let _ = lifecycle.complete(failure_for_platform_error(
                failure.clone(),
                BudgetConsumption::default(),
            ));
            return Err(failure);
        }
        Ok(InboundActivationReservation {
            envelope,
            lifecycle,
            manager: self.inner.clone(),
        })
    }
}

impl InboundActivationReservation {
    #[must_use]
    pub fn activation_id(&self) -> &ActivationId {
        &self.envelope.activation_id
    }

    #[must_use]
    pub fn revision(&self) -> &ResolvedRevision {
        self.envelope
            .resolved_revision
            .as_ref()
            .expect("inbound admission pins a revision")
    }

    #[must_use]
    pub fn deadline(&self) -> Instant {
        self.lifecycle
            .budget
            .as_ref()
            .expect("inbound admission grants a budget")
            .deadline()
            .monotonic()
            .expect("inbound transport deadline is finite")
    }

    /// The fixed allocation may be filled by a bounded codec; it cannot grow.
    pub fn input_buffer(&mut self) -> &mut [u8] {
        &mut self.envelope.input
    }

    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        let token = self.lifecycle.registration().token();
        if token.is_cancelled() {
            return Err(cancelled(&token));
        }
        if self.manager.clock.monotonic_now() >= self.deadline() {
            return Err(deadline_error());
        }
        Ok(())
    }

    /// Providers requiring a published capsule check this before each pull.
    /// The backend still performs its own final guarded activation-start check.
    pub fn publication_eligibility(&self) -> Result<ReleaseUseEligibility, PlatformError> {
        self.checkpoint()?;
        let revision = self.revision();
        let eligibility = self
            .manager
            .dependencies
            .artifacts
            .execution_eligibility_selected(&revision.release, revision.publication.as_ref())?
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::PermissionDenied,
                    "inbound publication required",
                )
            })?;
        eligibility.authorize_tenant(&revision.target.tenant)?;
        eligibility.check_current()?;
        Ok(eligibility)
    }

    /// Retains the exact grant, route and deadline. The length must describe the
    /// bytes actually written to the reserved buffer, not a network declaration.
    pub fn start(mut self, input_length: usize) -> Result<ActivationHandle, PlatformError> {
        if let Err(failure) = self.checkpoint() {
            return self.reject(failure);
        }
        if input_length > self.envelope.input.len() {
            return self.reject(error(
                PlatformErrorCode::InvalidArgument,
                "inbound input exceeds reservation",
            ));
        }
        self.envelope.input.truncate(input_length);
        Ok(handle(self.manager, self.envelope, self.lifecycle))
    }

    fn reject(self, failure: PlatformError) -> Result<ActivationHandle, PlatformError> {
        drop(self.envelope);
        let _ = self.lifecycle.complete(failure_for_platform_error(
            failure.clone(),
            BudgetConsumption::default(),
        ));
        Err(failure)
    }
}
