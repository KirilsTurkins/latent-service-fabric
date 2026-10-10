//! One bounded node-owned maintenance future. It never retains a Store or
//! activation, dials a destination, or creates per-connection tasks.
use crate::{StreamError, StreamLifecycle};
use latent_capabilities::broker::pools::ProviderMetadata;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Weak,
};
use std::time::{Duration, Instant};
use tokio::sync::Notify;

struct Stop {
    stopped: AtomicBool,
    changed: Notify,
    _metadata: ProviderMetadata,
}

pub struct StreamMaintenance {
    owner: Weak<StreamLifecycle>,
    stop: Arc<Stop>,
}

/// A stop acknowledgement cannot release the driver metadata. Its actual
/// future and every retained handle keep that allocation until real Drop.
#[derive(Clone)]
pub struct StreamMaintenanceStop(Arc<Stop>);

impl StreamMaintenance {
    pub(crate) fn new(owner: Weak<StreamLifecycle>, metadata: ProviderMetadata) -> Self {
        Self {
            owner,
            stop: Arc::new(Stop {
                stopped: AtomicBool::new(false),
                changed: Notify::new(),
                _metadata: metadata,
            }),
        }
    }

    #[must_use]
    pub fn stop_handle(&self) -> StreamMaintenanceStop {
        StreamMaintenanceStop(Arc::clone(&self.stop))
    }

    pub async fn run(self) -> Result<(), StreamError> {
        loop {
            let changed = self.stop.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if self.stop.stopped.load(Ordering::Acquire) {
                return Ok(());
            }
            // The temporary upgrade lasts only this finite synchronous scan.
            // No activation owner is carried across the driver's await.
            let finished = {
                let Some(owner) = self.owner.upgrade() else {
                    return Ok(());
                };
                match owner.maintenance_step(Instant::now()) {
                    Ok(finished) => finished,
                    Err(error) => {
                        owner.retire();
                        return Err(error);
                    }
                }
            };
            if finished {
                return Ok(());
            }
            tokio::select! {
                biased;
                () = changed => {},
                () = tokio::time::sleep(Duration::from_millis(10)) => {},
            }
        }
    }
}

impl StreamMaintenanceStop {
    pub fn stop(&self) {
        self.0.stopped.store(true, Ordering::Release);
        self.0.changed.notify_waiters();
    }
}

impl Drop for StreamMaintenance {
    fn drop(&mut self) {
        if let Some(owner) = self.owner.upgrade() {
            owner.release_maintenance();
        }
    }
}
