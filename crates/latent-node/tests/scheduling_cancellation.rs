use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Wake, Waker};

use latent_core::{ActivationId, CancelDisposition};
use latent_node::ActivationCancellationRegistry;
use latent_scheduler::SchedulingCancellation;

#[derive(Default)]
struct WakeCount(AtomicUsize);

impl Wake for WakeCount {
    fn wake(self: Arc<Self>) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }

    fn wake_by_ref(self: &Arc<Self>) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }
}

#[test]
fn scheduler_request_reaches_the_original_registration_and_executor_token() {
    let registry = ActivationCancellationRegistry::new(9).expect("bounded registry");
    let id = ActivationId("scheduler-request".to_owned());
    let registration = registry.register(id.clone()).expect("registered");
    let token = registration.token();
    let handle = registration.handle();
    let scheduling: &dyn SchedulingCancellation = &handle;

    assert_eq!(scheduling.activation_id(), &id);
    assert!(!scheduling.is_cancelled());
    assert!(scheduling.request_cancellation());
    assert!(!scheduling.request_cancellation());
    assert!(scheduling.is_cancelled());
    assert!(token.is_cancelled());
    assert_eq!(token.reason().as_deref(), Some("scheduler"));
    let registry_token = registry.token(&id).expect("same live registration");
    assert!(registry_token.is_cancelled());
    assert_eq!(registry_token.reason(), token.reason());
    assert_eq!(
        registry.cancel(&id, "upstream retry"),
        CancelDisposition::Accepted
    );
    assert_eq!(token.reason().as_deref(), Some("scheduler"));
    assert_eq!(registry.snapshot().active_registrations, 1);

    drop(registration);
    assert_eq!(registry.snapshot().active_registrations, 0);
}

#[test]
fn upstream_cancellation_wakes_the_scheduler_waiter_and_preserves_its_reason() {
    let registry = ActivationCancellationRegistry::default();
    let id = ActivationId("upstream-request".to_owned());
    let registration = registry.register(id.clone()).expect("registered");
    let handle = registration.handle();
    let scheduling: &dyn SchedulingCancellation = &handle;
    let wake_count = Arc::new(WakeCount::default());
    let waker = Waker::from(Arc::clone(&wake_count));
    let mut context = Context::from_waker(&waker);
    let mut waiting = scheduling.cancelled();

    assert!(waiting.as_mut().poll(&mut context).is_pending());
    assert_eq!(
        registry.cancel(&id, "caller cancelled"),
        CancelDisposition::Accepted
    );
    assert!(wake_count.0.load(Ordering::Relaxed) > 0);
    assert!(waiting.as_mut().poll(&mut context).is_ready());
    assert!(scheduling.is_cancelled());
    assert!(!scheduling.request_cancellation());
    assert_eq!(
        registration.token().reason().as_deref(),
        Some("caller cancelled")
    );
    assert!(scheduling
        .cancelled()
        .as_mut()
        .poll(&mut context)
        .is_ready());
}

#[test]
fn retained_scheduler_handle_does_not_cancel_a_new_registration_with_the_same_id() {
    let registry = ActivationCancellationRegistry::default();
    let id = ActivationId("reused-activation-id".to_owned());
    let old_registration = registry.register(id.clone()).expect("registered");
    let old_handle = old_registration.handle();
    drop(old_registration);
    let current_registration = registry.register(id.clone()).expect("registered again");

    assert!(SchedulingCancellation::request_cancellation(&old_handle));
    assert!(!current_registration.token().is_cancelled());
    assert!(!registry
        .token(&id)
        .expect("current registration")
        .is_cancelled());
    assert_eq!(registry.snapshot().active_registrations, 1);
}
