use super::*;
use crate::broker::http::{HttpBodyOwner, HttpMethod, HttpOwnedRequest, HttpRequest};
use crate::broker::io::HttpInputRetirement;
use std::{
    future::Future,
    panic::{catch_unwind, AssertUnwindSafe},
    sync::atomic::{AtomicBool, Ordering},
    task::{Context, Poll, Wake, Waker},
};

#[tokio::test]
async fn buffered_body_keeps_original_charge_during_actual_request_waker_panic() {
    struct PanicWake {
        budget: latent_core::ActivationBudget,
        io: Arc<IoRuntime>,
        baseline: u64,
        charge: u64,
        observed: Arc<AtomicBool>,
    }
    impl Wake for PanicWake {
        fn wake(self: Arc<Self>) {
            self.observed.store(
                self.budget.host_memory_bytes() >= self.baseline + self.charge
                    && self.io.snapshot().metadata_bytes >= self.charge as usize,
                Ordering::SeqCst,
            );
            panic!("controlled original pool-request waker panic");
        }
    }

    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, control) = setup.native_session_for(&setup.provider, "a", "http-owner-panic");
    let baseline = control.budget.host_memory_bytes();
    let initial_io = setup.pools.inner.io.snapshot();
    let call = setup.call(&session).await;
    let memory = call.io().reserve_scratch(64, 64).unwrap();
    let mut request = HttpOwnedRequest::preallocated(
        HttpRequest {
            method: HttpMethod::Post,
            url: "https://example.invalid/".into(),
            headers: Vec::new(),
            body: Some(b"resident".to_vec()),
            body_media_type: None,
            idempotency_key: None,
            timeout_millis: None,
        },
        Arc::new(memory),
    );
    let charge =
        (bytes::Bytes::owner_with_retirement_allocation_size::<HttpBodyOwner, HttpInputRetirement>(
        ) + 64) as u64;
    let bytes = request.take_body().into_http_bytes().unwrap();
    drop(request);
    drop(call); // the actual Bytes body now holds the original IoMemory lease
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);

    let observed = Arc::new(AtomicBool::new(false));
    let waker = Waker::from(Arc::new(PanicWake {
        budget: control.budget.clone(),
        io: Arc::clone(&setup.pools.inner.io),
        baseline,
        charge,
        observed: Arc::clone(&observed),
    }));
    let mut waiter = Box::pin(setup.pools.inner.changed.notified());
    waiter.as_mut().enable();
    assert!(matches!(
        waiter.as_mut().poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    let result = catch_unwind(AssertUnwindSafe(|| drop(bytes)));
    assert!(result.is_err());
    assert!(observed.load(Ordering::SeqCst));
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(setup.pools.inner.io.snapshot(), initial_io);
    drop(waiter);
    drop(waker);
    drop(session);
    clean(&setup.pools).await;
}
