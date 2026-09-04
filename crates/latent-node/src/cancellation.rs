use std::collections::HashMap;
use std::fmt;
use std::sync::{Arc, Mutex, MutexGuard};

use latent_core::{
    ActivationId, ActivationTerminalState, CancelDisposition, ErrorDetail, Metadata, PlatformError,
    PlatformErrorCode,
};
use latent_executor::{ExecutionCancellation, ExecutionCancellationProbe};
use tokio::sync::watch;

const DEFAULT_MAXIMUM_REASON_BYTES: usize = 256;
const DEFAULT_REASON: &str = "cancelled";

/// Constant-time observations for one activation cancellation registry.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CancellationRegistrySnapshot {
    pub active_registrations: u64,
}

/// Node-local, activation-keyed cancellation state.
///
/// Registrations are removed by their non-cloneable guard. Cancellation and
/// terminal publication share one linearized state transition: a cancellation
/// that wins first is idempotently accepted and determines a cancelled terminal
/// result, while a terminal publication that wins first is reported as
/// [`CancelDisposition::AlreadyTerminal`].
#[derive(Clone)]
pub struct ActivationCancellationRegistry {
    inner: Arc<RegistryInner>,
}

struct RegistryInner {
    maximum_reason_bytes: usize,
    registrations: Mutex<HashMap<ActivationId, Arc<CancellationState>>>,
}

impl fmt::Debug for ActivationCancellationRegistry {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ActivationCancellationRegistry")
            .field("maximum_reason_bytes", &self.inner.maximum_reason_bytes)
            .field("snapshot", &self.snapshot())
            .finish()
    }
}

impl Default for ActivationCancellationRegistry {
    fn default() -> Self {
        Self::new(DEFAULT_MAXIMUM_REASON_BYTES)
            .expect("the default cancellation reason bound is valid")
    }
}

impl ActivationCancellationRegistry {
    pub fn new(maximum_reason_bytes: usize) -> Result<Self, PlatformError> {
        if maximum_reason_bytes == 0 {
            return Err(registry_error(
                PlatformErrorCode::InvalidArgument,
                "cancellation reason bound must be non-zero",
                "activation.cancellation-invalid-configuration",
                Metadata::new(),
            ));
        }
        Ok(Self {
            inner: Arc::new(RegistryInner {
                maximum_reason_bytes,
                registrations: Mutex::new(HashMap::new()),
            }),
        })
    }

    /// Registers one live activation. Duplicate IDs are rejected before any
    /// activation work is delegated.
    pub fn register(
        &self,
        activation_id: ActivationId,
    ) -> Result<CancellationRegistration, PlatformError> {
        if activation_id.0.trim().is_empty() {
            return Err(registry_error(
                PlatformErrorCode::InvalidArgument,
                "activation ID must not be empty",
                "activation.cancellation-invalid-id",
                Metadata::new(),
            ));
        }
        let mut registrations = self.lock_registrations();
        if registrations.contains_key(&activation_id) {
            let fields = Metadata::from([("activation_id".to_owned(), activation_id.0.clone())]);
            return Err(registry_error(
                PlatformErrorCode::AlreadyExists,
                "activation already has a live cancellation registration",
                "activation.cancellation-duplicate-registration",
                fields,
            ));
        }
        let state = Arc::new(CancellationState::new(activation_id.clone()));
        registrations.insert(activation_id.clone(), Arc::clone(&state));
        Ok(CancellationRegistration {
            registry: self.clone(),
            activation_id,
            state,
        })
    }

    /// Cancels a registered activation. Repeated requests are accepted and do
    /// not replace the first reason.
    pub fn cancel(&self, activation_id: &ActivationId, reason: &str) -> CancelDisposition {
        let state = self.lock_registrations().get(activation_id).cloned();
        let Some(state) = state else {
            return CancelDisposition::NotFound;
        };
        match state.request_cancellation(self.bound_reason(reason)) {
            CancellationRequest::Installed | CancellationRequest::AlreadyAccepted => {
                CancelDisposition::Accepted
            }
            CancellationRequest::AlreadyTerminal(state) => {
                CancelDisposition::AlreadyTerminal(state)
            }
        }
    }

    #[must_use]
    pub fn token(&self, activation_id: &ActivationId) -> Option<CancellationToken> {
        self.lock_registrations()
            .get(activation_id)
            .cloned()
            .map(|state| CancellationToken { state })
    }

    #[must_use]
    pub fn snapshot(&self) -> CancellationRegistrySnapshot {
        CancellationRegistrySnapshot {
            active_registrations: u64::try_from(self.lock_registrations().len())
                .unwrap_or(u64::MAX),
        }
    }

    fn bound_reason(&self, reason: &str) -> String {
        let reason = if reason.trim().is_empty() {
            DEFAULT_REASON
        } else {
            reason
        };
        bounded_text(reason, self.inner.maximum_reason_bytes)
    }

    fn remove_if_current(&self, activation_id: &ActivationId, state: &Arc<CancellationState>) {
        let mut registrations = self.lock_registrations();
        if registrations
            .get(activation_id)
            .is_some_and(|current| Arc::ptr_eq(current, state))
        {
            registrations.remove(activation_id);
        }
    }

    fn lock_registrations(&self) -> MutexGuard<'_, HashMap<ActivationId, Arc<CancellationState>>> {
        self.inner
            .registrations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

/// Non-cloneable lifetime guard for one registry entry.
pub struct CancellationRegistration {
    registry: ActivationCancellationRegistry,
    activation_id: ActivationId,
    state: Arc<CancellationState>,
}

impl CancellationRegistration {
    #[must_use]
    pub fn activation_id(&self) -> &ActivationId {
        &self.activation_id
    }

    #[must_use]
    pub fn token(&self) -> CancellationToken {
        CancellationToken {
            state: Arc::clone(&self.state),
        }
    }

    #[must_use]
    pub fn handle(&self) -> CancellationHandle {
        CancellationHandle {
            state: Arc::clone(&self.state),
            maximum_reason_bytes: self.registry.inner.maximum_reason_bytes,
        }
    }

    /// Atomically publishes the terminal state against cancellation requests.
    /// A previously accepted cancellation changes the published state to
    /// `Cancelled`; a later cancellation observes `AlreadyTerminal`.
    pub(crate) fn publish_terminal(
        &self,
        proposed: ActivationTerminalState,
    ) -> TerminalPublication {
        self.state.publish_terminal(proposed)
    }
}

impl fmt::Debug for CancellationRegistration {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CancellationRegistration")
            .field("activation_id", &self.activation_id)
            .field("cancelled", &self.state.is_cancelled())
            .field("terminal_state", &self.state.terminal_state())
            .finish_non_exhaustive()
    }
}

impl Drop for CancellationRegistration {
    fn drop(&mut self) {
        self.registry
            .remove_if_current(&self.activation_id, &self.state);
    }
}

/// Cloneable mutation capability for one activation.
#[derive(Clone)]
pub struct CancellationHandle {
    state: Arc<CancellationState>,
    maximum_reason_bytes: usize,
}

impl CancellationHandle {
    #[must_use]
    pub fn activation_id(&self) -> &ActivationId {
        &self.state.activation_id
    }

    /// Returns `true` only for the request that installed the retained reason.
    /// A terminal activation and an already-accepted cancellation both return
    /// `false` without changing the retained state.
    pub fn cancel(&self, reason: &str) -> bool {
        let reason = if reason.trim().is_empty() {
            DEFAULT_REASON
        } else {
            reason
        };
        matches!(
            self.state
                .request_cancellation(bounded_text(reason, self.maximum_reason_bytes,)),
            CancellationRequest::Installed
        )
    }
}

impl fmt::Debug for CancellationHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CancellationHandle")
            .field("activation_id", &self.state.activation_id)
            .field("cancelled", &self.state.is_cancelled())
            .field("terminal_state", &self.state.terminal_state())
            .finish_non_exhaustive()
    }
}

/// Cloneable read-only cancellation view suitable for an executor/store.
#[derive(Clone)]
pub struct CancellationToken {
    state: Arc<CancellationState>,
}

impl CancellationToken {
    #[must_use]
    pub fn activation_id(&self) -> &ActivationId {
        &self.state.activation_id
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.state.is_cancelled()
    }

    #[must_use]
    pub fn reason(&self) -> Option<String> {
        self.state.reason()
    }

    pub async fn cancelled(&self) {
        self.state.cancelled().await;
    }
}

impl fmt::Debug for CancellationToken {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CancellationToken")
            .field("activation_id", &self.state.activation_id)
            .field("cancelled", &self.state.is_cancelled())
            .field("reason", &self.state.reason())
            .field("terminal_state", &self.state.terminal_state())
            .finish_non_exhaustive()
    }
}

impl ExecutionCancellationProbe for CancellationState {
    fn is_cancelled(&self) -> bool {
        self.is_cancelled()
    }

    fn reason(&self) -> Option<String> {
        self.reason()
    }
}

impl ExecutionCancellation for CancellationToken {
    fn activation_id(&self) -> &ActivationId {
        self.activation_id()
    }

    fn is_cancelled(&self) -> bool {
        self.is_cancelled()
    }

    fn reason(&self) -> Option<String> {
        self.reason()
    }

    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        Some(self.state.clone())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum CancellationLifecycle {
    Live,
    CancellationAccepted {
        reason: String,
    },
    Terminal {
        state: ActivationTerminalState,
        cancellation_reason: Option<String>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CancellationRequest {
    Installed,
    AlreadyAccepted,
    AlreadyTerminal(ActivationTerminalState),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TerminalPublication {
    pub state: ActivationTerminalState,
    pub cancellation_reason: Option<String>,
}

struct CancellationState {
    activation_id: ActivationId,
    lifecycle: Mutex<CancellationLifecycle>,
    signal: watch::Sender<bool>,
}

impl CancellationState {
    fn new(activation_id: ActivationId) -> Self {
        let (signal, _) = watch::channel(false);
        Self {
            activation_id,
            lifecycle: Mutex::new(CancellationLifecycle::Live),
            signal,
        }
    }

    fn request_cancellation(&self, reason: String) -> CancellationRequest {
        let transition = {
            let mut lifecycle = self.lock_lifecycle();
            match &*lifecycle {
                CancellationLifecycle::Live => {
                    *lifecycle = CancellationLifecycle::CancellationAccepted { reason };
                    CancellationRequest::Installed
                }
                CancellationLifecycle::CancellationAccepted { .. } => {
                    CancellationRequest::AlreadyAccepted
                }
                CancellationLifecycle::Terminal { state, .. } => {
                    CancellationRequest::AlreadyTerminal(*state)
                }
            }
        };
        if transition == CancellationRequest::Installed {
            self.signal.send_replace(true);
        }
        transition
    }

    fn publish_terminal(&self, proposed: ActivationTerminalState) -> TerminalPublication {
        let (publication, notify_cancelled) = {
            let mut lifecycle = self.lock_lifecycle();
            match &*lifecycle {
                CancellationLifecycle::Live => {
                    let publication = TerminalPublication {
                        state: proposed,
                        cancellation_reason: None,
                    };
                    *lifecycle = CancellationLifecycle::Terminal {
                        state: publication.state,
                        cancellation_reason: None,
                    };
                    (publication, proposed == ActivationTerminalState::Cancelled)
                }
                CancellationLifecycle::CancellationAccepted { reason } => {
                    let reason = reason.clone();
                    let publication = TerminalPublication {
                        state: ActivationTerminalState::Cancelled,
                        cancellation_reason: Some(reason.clone()),
                    };
                    *lifecycle = CancellationLifecycle::Terminal {
                        state: ActivationTerminalState::Cancelled,
                        cancellation_reason: Some(reason),
                    };
                    (publication, false)
                }
                CancellationLifecycle::Terminal {
                    state,
                    cancellation_reason,
                } => (
                    TerminalPublication {
                        state: *state,
                        cancellation_reason: cancellation_reason.clone(),
                    },
                    false,
                ),
            }
        };
        if notify_cancelled {
            self.signal.send_replace(true);
        }
        publication
    }

    fn is_cancelled(&self) -> bool {
        matches!(
            &*self.lock_lifecycle(),
            CancellationLifecycle::CancellationAccepted { .. }
                | CancellationLifecycle::Terminal {
                    state: ActivationTerminalState::Cancelled,
                    ..
                }
        )
    }

    fn reason(&self) -> Option<String> {
        match &*self.lock_lifecycle() {
            CancellationLifecycle::CancellationAccepted { reason } => Some(reason.clone()),
            CancellationLifecycle::Terminal {
                cancellation_reason,
                ..
            } => cancellation_reason.clone(),
            CancellationLifecycle::Live => None,
        }
    }

    fn terminal_state(&self) -> Option<ActivationTerminalState> {
        match &*self.lock_lifecycle() {
            CancellationLifecycle::Terminal { state, .. } => Some(*state),
            CancellationLifecycle::Live | CancellationLifecycle::CancellationAccepted { .. } => {
                None
            }
        }
    }

    async fn cancelled(&self) {
        let mut receiver = self.signal.subscribe();
        if *receiver.borrow() {
            return;
        }
        while receiver.changed().await.is_ok() {
            if *receiver.borrow() {
                return;
            }
        }
    }

    fn lock_lifecycle(&self) -> MutexGuard<'_, CancellationLifecycle> {
        self.lifecycle
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

fn bounded_text(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let mut end = maximum_bytes;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_owned()
}

fn registry_error(
    code: PlatformErrorCode,
    message: &str,
    kind: &str,
    fields: Metadata,
) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: vec![ErrorDetail {
            kind: kind.to_owned(),
            fields,
        }],
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Barrier;
    use std::thread;
    use std::time::Duration;

    use super::*;

    #[test]
    fn cancellation_is_idempotent_and_first_reason_wins() {
        let registry = ActivationCancellationRegistry::new(12).expect("valid registry");
        let id = ActivationId("activation-cancel".to_owned());
        let registration = registry.register(id.clone()).expect("registered");
        assert_eq!(
            registry.cancel(&id, "first-reason"),
            CancelDisposition::Accepted
        );
        assert_eq!(
            registry.cancel(&id, "second-reason"),
            CancelDisposition::Accepted
        );
        assert_eq!(
            registration.token().reason().as_deref(),
            Some("first-reason")
        );
    }

    #[test]
    fn concurrent_cancellation_has_one_linearization_winner() {
        let registry = ActivationCancellationRegistry::default();
        let id = ActivationId("activation-race".to_owned());
        let registration = registry.register(id).expect("registered");
        let winners = Arc::new(AtomicUsize::new(0));
        let mut workers = Vec::new();
        for index in 0..32 {
            let handle = registration.handle();
            let winners = Arc::clone(&winners);
            workers.push(thread::spawn(move || {
                if handle.cancel(&format!("reason-{index}")) {
                    winners.fetch_add(1, Ordering::Relaxed);
                }
            }));
        }
        for worker in workers {
            worker.join().expect("worker completes");
        }
        assert_eq!(winners.load(Ordering::Relaxed), 1);
        assert!(registration.token().reason().is_some());
    }

    #[test]
    fn terminal_publication_returns_already_terminal_until_removal() {
        let registry = ActivationCancellationRegistry::default();
        let id = ActivationId("activation-terminal".to_owned());
        let registration = registry.register(id.clone()).expect("registered");
        let publication = registration.publish_terminal(ActivationTerminalState::Completed);
        assert_eq!(publication.state, ActivationTerminalState::Completed);
        assert_eq!(publication.cancellation_reason, None);
        assert_eq!(
            registry.cancel(&id, "too late"),
            CancelDisposition::AlreadyTerminal(ActivationTerminalState::Completed)
        );
        drop(registration);
        assert_eq!(registry.cancel(&id, "removed"), CancelDisposition::NotFound);
    }

    #[test]
    fn cancellation_and_terminal_publication_have_one_linearization_winner() {
        for index in 0..256 {
            let registry = ActivationCancellationRegistry::default();
            let id = ActivationId(format!("activation-terminal-race-{index}"));
            let registration = Arc::new(registry.register(id.clone()).expect("registered"));
            let barrier = Arc::new(Barrier::new(3));

            let cancel_registry = registry.clone();
            let cancel_id = id.clone();
            let cancel_barrier = Arc::clone(&barrier);
            let cancel = thread::spawn(move || {
                cancel_barrier.wait();
                cancel_registry.cancel(&cancel_id, "race cancellation")
            });

            let publish_registration = Arc::clone(&registration);
            let publish_barrier = Arc::clone(&barrier);
            let publish = thread::spawn(move || {
                publish_barrier.wait();
                publish_registration.publish_terminal(ActivationTerminalState::Completed)
            });

            barrier.wait();
            let disposition = cancel.join().expect("cancellation racer completes");
            let publication = publish.join().expect("publication racer completes");
            match disposition {
                CancelDisposition::Accepted => {
                    assert_eq!(publication.state, ActivationTerminalState::Cancelled);
                    assert_eq!(
                        publication.cancellation_reason.as_deref(),
                        Some("race cancellation")
                    );
                }
                CancelDisposition::AlreadyTerminal(ActivationTerminalState::Completed) => {
                    assert_eq!(publication.state, ActivationTerminalState::Completed);
                    assert_eq!(publication.cancellation_reason, None);
                }
                other => panic!("unexpected cancellation race disposition: {other:?}"),
            }
            assert_eq!(
                registry.cancel(&id, "after publication"),
                CancelDisposition::AlreadyTerminal(publication.state)
            );
        }
    }

    #[tokio::test]
    async fn token_observes_signal_and_reason() {
        let registry = ActivationCancellationRegistry::default();
        let id = ActivationId("activation-observe".to_owned());
        let registration = registry.register(id).expect("registered");
        let token = registration.token();
        let handle = registration.handle();
        let waiter = tokio::spawn(async move {
            token.cancelled().await;
            token.reason()
        });
        tokio::time::sleep(Duration::from_millis(1)).await;
        assert!(handle.cancel("observable"));
        let reason = waiter.await.expect("waiter joins");
        assert_eq!(reason.as_deref(), Some("observable"));
    }

    #[test]
    fn registration_drop_removes_the_activation() {
        let registry = ActivationCancellationRegistry::default();
        let id = ActivationId("activation-drop".to_owned());
        let registration = registry.register(id.clone()).expect("registered");
        assert_eq!(registry.snapshot().active_registrations, 1);
        drop(registration);
        assert_eq!(registry.snapshot().active_registrations, 0);
        assert_eq!(
            registry.cancel(&id, "too late"),
            CancelDisposition::NotFound
        );
    }

    #[test]
    fn bounded_reason_preserves_utf8_boundaries() {
        let registry = ActivationCancellationRegistry::new(5).expect("valid registry");
        let id = ActivationId("activation-utf8".to_owned());
        let registration = registry.register(id.clone()).expect("registered");
        assert_eq!(registry.cancel(&id, "ééé"), CancelDisposition::Accepted);
        assert_eq!(registration.token().reason().as_deref(), Some("éé"));
    }
}
