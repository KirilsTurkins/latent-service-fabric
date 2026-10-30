//! Explicit timing on the node's existing executor; never execution authority.

use std::time::Instant;

use latent_core::{ActivationBudget, BoxFuture, PlatformError};
use latent_executor::{OwnedPreparationWait, PreparationReadWait};

/// Caller-supplied timer for bounded currentness acquisition. This zero-sized
/// adapter owns no task, thread, queue or runtime. Its caller must poll it on
/// the node's existing Tokio executor with time enabled. Each returned sleep
/// belongs to the calling future and unregisters when that future is dropped.
/// Preparation and clock imports keep their own original deadline, cancellation
/// and authority checks; a timer can neither grant access nor replay work.
pub struct CurrentnessReadTimer;

impl PreparationReadWait for CurrentnessReadTimer {
    fn now(&self) -> Instant {
        tokio::time::Instant::now().into_std()
    }

    fn wait_until(&self, deadline: Instant) -> BoxFuture<'_, ()> {
        Box::pin(tokio::time::sleep_until(deadline.into()))
    }

    fn wait_until_owned<'a>(
        &'a self,
        deadline: Instant,
        budget: &ActivationBudget,
    ) -> Result<OwnedPreparationWait<'a>, PlatformError> {
        // Only the actual Sleep Box is prepaid here, before Sleep construction.
        // Under the pinned traditional timer, TimerEntry/TimerShared are inline
        // and native Drop unregisters before this Box is deallocated. Existing
        // paid caller Wakers retain their own charge. This does not certify
        // arbitrary tracing/alternative timer or shared driver allocations.
        OwnedPreparationWait::try_boxed(budget, || tokio::time::sleep_until(deadline.into()))
    }
}
