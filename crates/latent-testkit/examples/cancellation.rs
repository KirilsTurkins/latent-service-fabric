//! cargo run -p latent-testkit --no-default-features --example cancellation --locked
use std::sync::Arc;

use latent_testkit::coordination::{
    with_watchdog, CoordinationError, PollProbe, Rendezvous, Stage, WATCHDOG,
};

#[tokio::main(flavor = "current_thread")]
async fn main() {
    with_watchdog(WATCHDOG, async {
        let rendezvous = Rendezvous::new(1);
        let buffer = Arc::new(vec![0_u8; 16]);
        let weak = Arc::downgrade(&buffer);
        let (id, mut work) = rendezvous.track(buffer).unwrap();
        // The worker now owns the actual buffer. Record entry after that handoff.
        work.commit(Stage::Entered).unwrap();
        let mut future = Box::pin(async move {
            work.pause().await;
            drop(work);
        });
        PollProbe::default().pending(future.as_mut());
        rendezvous.blocked(id, Stage::Entered).unwrap();
        assert_eq!(weak.strong_count(), 1);
        assert_eq!(rendezvous.require_retired(id), Err(CoordinationError::WrongStage));
        let task = tokio::spawn(future);
        task.abort();
        // abort() requests cancellation; joining proves that this owner was dropped.
        assert!(task.await.unwrap_err().is_cancelled());
        rendezvous.require_retired(id).unwrap();
        assert!(weak.upgrade().is_none());
        assert_eq!(rendezvous.live_owners(), 0);
    }).await;
}
