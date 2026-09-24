use super::diagnostics::{self, Reason, Recorder};
use latent_activation::ActivationOutcome;
use latent_core::{
    ActivationTerminalState, BoxFuture, BudgetConsumption, ErrorDetail, PlatformError,
    PlatformErrorCode,
};
use std::{
    future::Future,
    pin::Pin,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    task::{Context, Poll},
};

pub const PRIVATE: &str = "private-token /private/path secret payload";

pub fn error(message: &str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: message.into(),
        retryable: true,
        details: vec![],
    }
}

pub fn detail_error(kind: &str, reason: &str) -> PlatformError {
    let mut failure = error(PRIVATE);
    failure.details.push(ErrorDetail {
        kind: kind.into(),
        fields: [("reason".into(), reason.into())].into(),
    });
    failure
}

pub fn consumption() -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: 123,
        wall_time_micros: 456,
        ..Default::default()
    }
}

pub fn failed(error: PlatformError) -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::DependencyFailed,
        error,
        consumption: consumption(),
    }
}

pub struct DropOwner(pub Arc<AtomicUsize>);
impl Drop for DropOwner {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }
}

pub struct FakeCompletion {
    pub outcome: ActivationOutcome,
    pub owner: DropOwner,
}
impl FakeCompletion {
    pub fn new(outcome: ActivationOutcome) -> Self {
        Self {
            outcome,
            owner: DropOwner(Arc::new(AtomicUsize::new(0))),
        }
    }
}

type Invocation = BoxFuture<'static, Result<FakeCompletion, PlatformError>>;

pub struct FakeInvoker {
    pub starts: usize,
    pub polls: Arc<AtomicUsize>,
    pub drops: Arc<AtomicUsize>,
    result: Option<Result<Invocation, PlatformError>>,
}
impl FakeInvoker {
    pub fn rejected(error: PlatformError) -> Self {
        Self {
            starts: 0,
            polls: Arc::default(),
            drops: Arc::default(),
            result: Some(Err(error)),
        }
    }
    pub fn ready(result: Result<FakeCompletion, PlatformError>) -> Self {
        Self::with_future(result, false)
    }
    pub fn pending(completion: FakeCompletion) -> Self {
        Self::with_future(Ok(completion), true)
    }
    fn with_future(result: Result<FakeCompletion, PlatformError>, pending: bool) -> Self {
        let polls = Arc::default();
        let drops = Arc::default();
        let invocation = FakeInvocation {
            polls: Arc::clone(&polls),
            drops: Arc::clone(&drops),
            result: Some(result),
            pending,
        };
        Self {
            starts: 0,
            polls,
            drops,
            result: Some(Ok(Box::pin(invocation))),
        }
    }
    pub fn observed(&mut self, recorder: Arc<Recorder>) -> Result<Invocation, PlatformError> {
        diagnostics::observe_start(
            recorder,
            || {
                self.starts += 1;
                self.result
                    .take()
                    .expect("the original invoker must only be started once")
            },
            |completion| &completion.outcome,
        )
    }
}

struct FakeInvocation {
    polls: Arc<AtomicUsize>,
    drops: Arc<AtomicUsize>,
    result: Option<Result<FakeCompletion, PlatformError>>,
    pending: bool,
}
impl Future for FakeInvocation {
    type Output = Result<FakeCompletion, PlatformError>;
    fn poll(mut self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Self::Output> {
        self.polls.fetch_add(1, Ordering::Relaxed);
        if self.pending {
            Poll::Pending
        } else {
            Poll::Ready(self.result.take().unwrap())
        }
    }
}
impl Drop for FakeInvocation {
    fn drop(&mut self) {
        self.drops.fetch_add(1, Ordering::Relaxed);
    }
}

pub fn assert_reason(error: PlatformError, reason: Reason) {
    let recorder = Arc::new(Recorder::default());
    let code = error.code;
    let message = error.message.as_ptr();
    let mut invoker = FakeInvoker::rejected(error);
    let returned = invoker.observed(recorder.clone()).err().unwrap();
    assert_eq!(returned.message.as_ptr(), message);
    assert_eq!(invoker.starts, 1);
    let snapshot = recorder.snapshot();
    assert_eq!(snapshot.records.len(), 1);
    assert_eq!(snapshot.records[0].reason, reason);
    assert_eq!(snapshot.records[0].code, code);
    assert!(!snapshot.incomplete);
    let diagnostic = format!("{snapshot:?}");
    for private in ["private-token", "/private/path", "secret payload"] {
        assert!(!diagnostic.contains(private));
    }
}

pub fn assert_forwarded_error(recorder: Arc<Recorder>) {
    let original = detail_error("admission.currentness", "admission-authority-busy");
    let message = original.message.as_ptr();
    let mut invoker = FakeInvoker::rejected(original);
    let returned = invoker.observed(recorder).err().unwrap();
    assert_eq!(returned.message.as_ptr(), message);
    assert_eq!(
        returned,
        detail_error("admission.currentness", "admission-authority-busy")
    );
    assert_eq!(invoker.starts, 1);
}
