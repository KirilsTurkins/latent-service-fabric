//! Test-only observation before the service adapter lowers private child errors.
//! No error text or payload is retained, and observation cannot retry or reject work.
use latent_activation::ActivationOutcome;
use latent_capabilities::broker::{
    LocalServiceInvocation, LocalServiceInvoker, LocalServiceRequest, ProviderCall,
};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};

#[path = "diagnostics/reason.rs"]
mod reason;
pub use reason::Reason;

pub const MAX_RECORDS: usize = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    Start,
    InvocationError,
    ChildFailure,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FailureRecord {
    pub stage: Stage,
    pub code: PlatformErrorCode,
    pub reason: Reason,
}

#[derive(Debug, PartialEq, Eq)]
pub struct Snapshot {
    pub records: Vec<FailureRecord>,
    pub incomplete: bool,
}

pub struct Recorder {
    // Visible only inside integration-test crates so the fake-invoker tests can
    // prove that contended and poisoned observation storage never rejects work.
    pub storage: Mutex<[Option<FailureRecord>; MAX_RECORDS]>,
    incomplete: AtomicBool,
}

impl Default for Recorder {
    fn default() -> Self {
        Self {
            storage: Mutex::new([None; MAX_RECORDS]),
            incomplete: AtomicBool::new(false),
        }
    }
}

impl Recorder {
    fn record(&self, stage: Stage, error: &PlatformError) {
        let record = FailureRecord {
            stage,
            code: error.code,
            reason: reason::classify(error),
        };
        if let Ok(mut records) = self.storage.try_lock() {
            if let Some(slot) = records.iter_mut().find(|slot| slot.is_none()) {
                *slot = Some(record);
                return;
            }
        }
        self.incomplete.store(true, Ordering::Relaxed);
    }

    pub fn snapshot(&self) -> Snapshot {
        let records = if let Ok(records) = self.storage.try_lock() {
            records.iter().flatten().copied().collect()
        } else {
            self.incomplete.store(true, Ordering::Relaxed);
            Vec::new()
        };
        Snapshot {
            records,
            incomplete: self.incomplete.load(Ordering::Relaxed),
        }
    }
}

pub struct ObservedInvoker {
    pub inner: Arc<dyn LocalServiceInvoker>,
    pub recorder: Arc<Recorder>,
}

impl LocalServiceInvoker for ObservedInvoker {
    fn start(
        &self,
        call: ProviderCall,
        request: LocalServiceRequest,
    ) -> Result<LocalServiceInvocation, PlatformError> {
        observe_start(
            self.recorder.clone(),
            || self.inner.start(call, request),
            |completion| &completion.outcome,
        )
    }
}

/// The same once-only forwarding seam is exercised with fake invokers without
/// manufacturing trusted provider calls or child budget owners. Only a borrowed
/// outcome is classified; the original completion/error and its owners move on.
pub fn observe_start<C: Send + 'static>(
    recorder: Arc<Recorder>,
    start: impl FnOnce() -> Result<BoxFuture<'static, Result<C, PlatformError>>, PlatformError>,
    outcome: fn(&C) -> &ActivationOutcome,
) -> Result<BoxFuture<'static, Result<C, PlatformError>>, PlatformError> {
    let invocation = match start() {
        Ok(invocation) => invocation,
        Err(error) => {
            recorder.record(Stage::Start, &error);
            return Err(error);
        }
    };
    Ok(Box::pin(async move {
        let result = invocation.await;
        match &result {
            Ok(completion) => {
                if let ActivationOutcome::Failed { error, .. } = outcome(completion) {
                    recorder.record(Stage::ChildFailure, error);
                }
            }
            Err(error) => recorder.record(Stage::InvocationError, error),
        }
        result
    }))
}
