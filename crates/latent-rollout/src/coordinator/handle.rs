use super::RolloutHandle;
use crate::{
    capacity, closed, deadline, invalid,
    ticket::{Completion, Control},
    worker::{Command, Job, MutationInput},
    CoordinatorLimits, CoordinatorSnapshot, MutationPreview, MutationResult, Result, RolloutTicket,
};
use latent_audit::AuditHandle;
use latent_control_store::rollouts::{
    RolloutId, RolloutLimits, RolloutOperationLookup, RolloutPage, RolloutPageRequest,
    RolloutRequest, RolloutStatus,
};
use latent_core::TenantId;
use std::{mem::size_of, sync::Arc, time::Instant};
use tokio::sync::oneshot;

impl RolloutHandle {
    #[must_use]
    pub fn limits(&self) -> CoordinatorLimits {
        self.owner.shared.limits
    }
    #[must_use]
    pub fn rollout_limits(&self) -> RolloutLimits {
        self.owner.store_limits
    }
    #[must_use]
    pub fn audit_owner_matches(&self, audit: &AuditHandle) -> bool {
        self.owner.audit.same_owner(audit)
    }
    #[must_use]
    pub fn snapshot(&self) -> CoordinatorSnapshot {
        self.owner.shared.snapshot()
    }
    pub fn close(&self) {
        self.owner.close();
    }

    /// The trusted adapter's callback is reject-only, bounded and nonblocking;
    /// its captures must not retain uncharged request data or external owners.
    pub fn submit<F>(
        &self,
        request: RolloutRequest,
        expires: Instant,
        preflight: F,
    ) -> Result<RolloutTicket<MutationResult>>
    where
        F: for<'a> FnOnce(MutationPreview<'a>) -> Result<()> + Send + 'static,
    {
        request.validate(self.rollout_limits())?;
        let bytes = request
            .retained_bytes()
            .checked_add(size_of::<F>())
            .ok_or_else(|| capacity("rollout-request-size"))?;
        self.enqueue(
            MutationInput {
                request,
                preflight: Box::new(preflight),
            },
            bytes,
            self.limits().maximum_page_bytes,
            expires,
            |job| Command::Mutation(Box::new(job)),
        )
    }

    pub fn get(
        &self,
        tenant: TenantId,
        id: RolloutId,
        expires: Instant,
    ) -> Result<RolloutTicket<Option<RolloutStatus>>> {
        text(&tenant.0, 256)?;
        text(&id.0, 128)?;
        let bytes = size_of::<(TenantId, RolloutId)>() + tenant.0.capacity() + id.0.capacity();
        self.enqueue(
            (tenant, id),
            bytes,
            self.limits().maximum_page_bytes,
            expires,
            Command::Get,
        )
    }

    pub fn list(
        &self,
        request: RolloutPageRequest,
        expires: Instant,
    ) -> Result<RolloutTicket<RolloutPage>> {
        text(&request.tenant.0, 256)?;
        if let Some(service) = &request.service {
            text(&service.0, 256)?;
        }
        if let Some(cursor) = &request.cursor {
            text(cursor, 512)?;
        }
        if request.limit == 0
            || request.limit > self.rollout_limits().maximum_rows.min(128)
            || request.maximum_bytes < 4096
        {
            return Err(invalid("rollout-page-limit"));
        }
        let bytes = size_of::<RolloutPageRequest>()
            + request.tenant.0.capacity()
            + request.service.as_ref().map_or(0, |s| s.0.capacity())
            + request.cursor.as_ref().map_or(0, String::capacity);
        let maximum = request.maximum_bytes;
        self.enqueue(request, bytes, maximum, expires, Command::List)
    }

    pub fn operation(
        &self,
        tenant: TenantId,
        id: RolloutId,
        operation_id: String,
        expires: Instant,
    ) -> Result<RolloutTicket<RolloutOperationLookup>> {
        text(&tenant.0, 256)?;
        text(&id.0, 128)?;
        text(&operation_id, 128)?;
        let bytes = size_of::<(TenantId, RolloutId, String)>()
            + tenant.0.capacity()
            + id.0.capacity()
            + operation_id.capacity();
        self.enqueue(
            (tenant, id, operation_id),
            bytes,
            self.limits().maximum_page_bytes,
            expires,
            Command::Operation,
        )
    }

    fn enqueue<I, O>(
        &self,
        input: I,
        bytes: usize,
        maximum: usize,
        expires: Instant,
        wrap: impl FnOnce(Job<I, O>) -> Command,
    ) -> Result<RolloutTicket<O>> {
        if Instant::now() >= expires {
            return Err(deadline());
        }
        let sender = self.owner.sender.lock().map_err(|_| closed())?;
        let sender = sender.as_ref().ok_or_else(closed)?;
        let lease = self.owner.shared.pages.reserve(maximum)?;
        let charge = self.owner.shared.reserve(bytes)?;
        let control = Control::new();
        let (reply, receiver): (oneshot::Sender<Completion<O>>, _) = oneshot::channel();
        let command = wrap(Job {
            input: Some(input),
            reply: Some(reply),
            control: Arc::clone(&control),
            expires,
            maximum,
            lease: Some(lease),
            charge,
        });
        sender
            .try_send(command)
            .map_err(|_| capacity("rollout-command-queue"))?;
        Ok(RolloutTicket::new(receiver, control, expires))
    }
}

fn text(value: &String, maximum: usize) -> Result<()> {
    if value.is_empty()
        || value.len() > maximum
        || value.capacity() > maximum
        || value.trim() != value
        || value
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        return Err(invalid("rollout-query-identity"));
    }
    Ok(())
}
