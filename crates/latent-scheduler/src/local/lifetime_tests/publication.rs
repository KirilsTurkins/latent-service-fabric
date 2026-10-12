//! A received parent assignment can synchronously attempt an immediate child.
use std::future::Future;
use std::pin::pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Wake, Waker};

use latent_core::PlatformError;
use tokio::sync::oneshot;

use super::{AdmittedSchedulingRequest, Cancellation, Fixture};
use crate::local::LocalScheduler;
use crate::{ActivationScheduler, CellClass, ScheduledActivation};

struct ImmediateCaller {
    scheduler: Arc<LocalScheduler>,
    request: Mutex<Option<AdmittedSchedulingRequest>>,
    result: Mutex<Option<Result<ScheduledActivation, PlatformError>>>,
    wakes: AtomicUsize,
}

impl Wake for ImmediateCaller {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }

    fn wake_by_ref(self: &Arc<Self>) {
        if let Some(request) = self.request.lock().unwrap().take() {
            self.wakes.fetch_add(1, Ordering::SeqCst);
            *self.result.lock().unwrap() = Some(self.scheduler.try_enqueue(request));
        }
    }
}

#[tokio::test]
async fn published_parent_can_immediately_use_the_other_available_cell() {
    let fixture = Fixture::new(1, 2).unwrap();
    let capacity = fixture.scheduler.observations(CellClass::Standard).capacity;
    assert!(capacity >= 2);
    let caller = Arc::new(ImmediateCaller {
        scheduler: Arc::clone(&fixture.scheduler),
        request: Mutex::new(Some(AdmittedSchedulingRequest {
            permit: fixture.admit(1, 0).unwrap(),
            cancellation: Cancellation::new(1),
        })),
        result: Mutex::new(None),
        wakes: AtomicUsize::new(0),
    });
    let (sender, receiver) = oneshot::channel();
    fixture
        .scheduler
        .register_request(
            CellClass::Standard,
            AdmittedSchedulingRequest {
                permit: fixture.admit(0, 0).unwrap(),
                cancellation: Cancellation::new(0),
            },
            sender,
        )
        .unwrap();
    let mut receiver = pin!(receiver);
    let waker = Waker::from(Arc::clone(&caller));
    assert!(matches!(
        receiver.as_mut().poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    fixture.scheduler.inner.pump(CellClass::Standard);
    let parent = receiver.await.unwrap().unwrap().accept().unwrap();
    let child = caller
        .result
        .lock()
        .unwrap()
        .take()
        .expect("actual assignment publication wakes its caller")
        .expect("an available second cell is not dispatch-lock capacity exhaustion");
    assert_eq!(caller.wakes.load(Ordering::SeqCst), 1);
    assert_eq!(
        fixture
            .scheduler
            .observations(CellClass::Standard)
            .active_leases,
        2
    );
    child.release().await.unwrap();
    parent.release().await.unwrap();
    let idle = fixture.scheduler.observations(CellClass::Standard);
    assert_eq!(idle.active_leases, 0);
    assert_eq!(idle.queue_depth, 0);
    assert_eq!(idle.available, capacity);
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 0);
}
