use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::AtomicUsize;
use std::sync::{Arc, Weak};
use std::task::{Context, Poll, Wake, Waker};

use latent_core::ActivationId;
use latent_executor::ExecutionCancellationProbe;
use latent_scheduler::SchedulingCancellation;

use super::*;
use crate::activation_manager::probes::ActivationControl;
use crate::ActivationCancellationRegistry;

struct WakeCheck {
    stop: Weak<TransportStop>,
    wakes: AtomicUsize,
}

impl Wake for WakeCheck {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }

    fn wake_by_ref(self: &Arc<Self>) {
        assert!(self.stop.upgrade().unwrap().cause().is_some());
        self.wakes.fetch_add(1, Ordering::Relaxed);
    }
}

#[test]
fn marking_wakes_every_registered_view_once_and_keeps_the_first_cause() {
    let stop = Arc::new(TransportStop::default());
    let observation = Arc::new(WakeCheck {
        stop: Arc::downgrade(&stop),
        wakes: AtomicUsize::new(0),
    });
    let waker = Waker::from(observation.clone());
    let mut context = Context::from_waker(&waker);
    let mut first = Box::pin(stop.interrupted());
    let mut second = Box::pin(stop.interrupted());
    assert!(first.as_mut().poll(&mut context).is_pending());
    assert!(second.as_mut().poll(&mut context).is_pending());
    stop.mark(ActivationTransportInterruption::Disconnected);
    assert_eq!(observation.wakes.load(Ordering::Relaxed), 2);
    assert!(first.as_mut().poll(&mut context).is_ready());
    assert!(second.as_mut().poll(&mut context).is_ready());
    stop.mark(ActivationTransportInterruption::DeadlineExceeded);
    assert_eq!(observation.wakes.load(Ordering::Relaxed), 2);
    assert_eq!(stop.failure().unwrap().code, PlatformErrorCode::Cancelled);
    // A mark before registration is observed without another notification.
    let mut late = Box::pin(stop.interrupted());
    assert!(late.as_mut().poll(&mut context).is_ready());
}

fn poll<F: Future + ?Sized>(future: Pin<&mut F>) -> Poll<F::Output> {
    future.poll(&mut Context::from_waker(Waker::noop()))
}

#[test]
fn raw_disconnect_stops_both_probes_without_accepting_explicit_cancellation() {
    let registry = ActivationCancellationRegistry::default();
    let registration = registry.register(ActivationId("raw-stop".into())).unwrap();
    let stop = Arc::new(TransportStop::default());
    let probe = ActivationControl::new(&registration, stop.clone());
    let mut waiting = SchedulingCancellation::cancelled(&probe);
    assert!(poll(waiting.as_mut()).is_pending());
    stop.mark(ActivationTransportInterruption::Disconnected);
    assert!(poll(waiting.as_mut()).is_ready());
    assert!(ExecutionCancellationProbe::is_cancelled(&probe));
    assert!(SchedulingCancellation::is_cancelled(&probe));
    assert!(!registration.token().is_cancelled());
    assert_eq!(registration.token().reason(), None);
    assert_eq!(probe.token().activation_id(), registration.activation_id());
    assert_eq!(registry.snapshot().active_registrations, 1);
    assert!(SchedulingCancellation::request_cancellation(&probe));
    assert_eq!(probe.reason().as_deref(), Some("scheduler cancellation"));
    assert!(!SchedulingCancellation::request_cancellation(&probe));
}

#[test]
fn deadline_mark_is_not_a_cancellation_probe_or_a_repeating_ready_wait() {
    let registry = ActivationCancellationRegistry::default();
    let registration = registry
        .register(ActivationId("deadline-stop".into()))
        .unwrap();
    let stop = Arc::new(TransportStop::default());
    let probe = ActivationControl::new(&registration, stop.clone());
    let mut waiting = SchedulingCancellation::cancelled(&probe);
    assert!(poll(waiting.as_mut()).is_pending());
    stop.mark(ActivationTransportInterruption::DeadlineExceeded);
    assert!(poll(waiting.as_mut()).is_pending());
    assert!(poll(waiting.as_mut()).is_pending());
    assert!(!ExecutionCancellationProbe::is_cancelled(&probe));
    assert!(!SchedulingCancellation::is_cancelled(&probe));
    assert_eq!(probe.reason(), None);
    assert_eq!(
        stop.failure().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert!(registration
        .handle()
        .cancel("explicit after transport expiry"));
    assert!(poll(waiting.as_mut()).is_ready());
    assert!(probe.stopped());
}
