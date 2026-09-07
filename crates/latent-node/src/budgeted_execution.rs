//! Captures activation-owned accounting before crossing the execution boundary.

use std::sync::Arc;

use latent_artifacts::CapsuleArtifact;
use latent_core::{
    ActivationBudget, ActivationId, BoxFuture, BudgetError, PlatformError, PlatformErrorCode,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionCancellationProbe, ExecutionReport,
    ExecutionRequest, GuestOutcome, PreparationKey, PreparedComponent,
};

use crate::ActivationBudgetRegistry;

/// Optional bridge from an activation owner's registry to any execution backend.
/// A lookup occurs once per invocation; the captured handle survives registry
/// removal without becoming attached to a later activation reusing the same ID.
pub struct BudgetedExecutionBackend {
    inner: Arc<dyn ExecutionBackend>,
    budgets: ActivationBudgetRegistry,
}

impl BudgetedExecutionBackend {
    #[must_use]
    pub fn new(inner: Arc<dyn ExecutionBackend>, budgets: ActivationBudgetRegistry) -> Self {
        Self { inner, budgets }
    }

    fn capture(
        &self,
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
    ) -> Result<Option<ActivationBudget>, PlatformError> {
        if cancellation.activation_id() != &request.activation.activation_id {
            return Err(invalid(
                "execution cancellation belongs to another activation",
            ));
        }
        let registered = self.budgets.get(&request.activation.activation_id);
        let supplied = cancellation.budget_accounting();
        if let (Some(registered), Some(supplied)) = (&registered, supplied) {
            if !registered.is_same_instance(supplied) {
                return Err(invalid("execution-budget-owner-mismatch"));
            }
        }
        let budget = registered.or_else(|| supplied.cloned());
        if let Some(budget) = &budget {
            if budget.granted() != &request.budget || request.budget != request.activation.budget {
                return Err(invalid("execution-budget-grant-mismatch"));
            }
            if budget.finalization().is_some() {
                return Err(BudgetError::AccountingFinalized.to_platform_error());
            }
        }
        Ok(budget)
    }
}

struct CapturedCancellation<'a> {
    inner: &'a dyn ExecutionCancellation,
    budget: Option<ActivationBudget>,
}

impl ExecutionCancellation for CapturedCancellation<'_> {
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
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        self.budget.as_ref()
    }
    fn effective_deadline(&self) -> Option<&latent_core::EffectiveDeadline> {
        let owned = self.budget.as_ref().map(ActivationBudget::deadline);
        match (owned, self.inner.effective_deadline()) {
            (Some(owned), Some(supplied))
                if supplied.monotonic().is_some_and(|supplied| {
                    owned.monotonic().is_none_or(|current| supplied < current)
                }) =>
            {
                Some(supplied)
            }
            (Some(owned), _) => Some(owned),
            (None, supplied) => supplied,
        }
    }
}

impl ExecutionBackend for BudgetedExecutionBackend {
    fn backend_id(&self) -> &str {
        self.inner.backend_id()
    }

    fn prepare<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        self.inner.prepare(artifact, key)
    }

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move {
            let budget = self.capture(&request, cancellation)?;
            self.inner
                .invoke(
                    request,
                    &CapturedCancellation {
                        inner: cancellation,
                        budget,
                    },
                )
                .await
        })
    }

    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let budget = match self.capture(&request, cancellation) {
                Ok(budget) => budget,
                Err(error) => return ExecutionReport::reusable(Err(error)),
            };
            self.inner
                .invoke_contained(
                    request,
                    &CapturedCancellation {
                        inner: cancellation,
                        budget,
                    },
                )
                .await
        })
    }

    fn release(&self, prepared: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.inner.release(prepared)
    }
}

fn invalid(message: &str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests;
