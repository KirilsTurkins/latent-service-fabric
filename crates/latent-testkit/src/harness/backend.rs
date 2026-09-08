use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome};
use latent_core::{ActivationTerminalState, BoxFuture, BudgetConsumption};
use latent_executor::ExecutionBackend;

use crate::{conformance::WorkCounter, BackendHarness};

/// Exposes a caller-owned backend and invokes through its caller-owned manager.
/// The caller must supply the manager that actually uses this backend; this
/// adapter does not create or inspect the manager's dependency graph.
pub struct BorrowedBackendHarness<'a> {
    backend: &'a dyn ExecutionBackend,
    manager: &'a dyn ActivationManager,
    work: WorkCounter,
}

impl<'a> BorrowedBackendHarness<'a> {
    #[must_use]
    pub fn new(
        backend: &'a dyn ExecutionBackend,
        manager: &'a dyn ActivationManager,
        work: WorkCounter,
    ) -> Self {
        Self {
            backend,
            manager,
            work,
        }
    }
}

impl BackendHarness for BorrowedBackendHarness<'_> {
    fn backend(&self) -> &dyn ExecutionBackend {
        self.backend
    }

    /// Charges once before calling the manager, including synchronous start.
    /// Callers sharing this work counter must not charge the same call again.
    fn invoke(&self, envelope: ActivationEnvelope) -> BoxFuture<'_, ActivationOutcome> {
        if self.work.before_command(true).is_err() {
            return Box::pin(std::future::ready(ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::Rejected,
                error: super::work_limit(),
                consumption: BudgetConsumption::default(),
            }));
        }
        self.manager.invoke(envelope)
    }
}
