//! Affine backend-owned preparation without runtime-specific executor types.

use std::any::Any;
use std::fmt;

use crate::PreparedComponent;

/// One immutable prepared-state pin. Unlike a descriptor, this value owns the
/// state needed to execute despite shared-cache eviction. Dropping it releases
/// its backend guard synchronously; it never performs asynchronous cache release.
#[must_use = "dropping the prepared use immediately releases its runtime pin"]
pub struct PreparedUse {
    descriptor: Box<PreparedComponent>,
    ownership: Box<dyn Any + Send + Sync>,
}

impl PreparedUse {
    /// Backend extension point. `ownership` must retain only immutable prepared
    /// state and bounded reservations, and release them synchronously on drop.
    pub fn new<T: Any + Send + Sync>(descriptor: PreparedComponent, ownership: T) -> Self {
        Self {
            descriptor: Box::new(descriptor),
            ownership: Box::new(ownership),
        }
    }

    #[must_use]
    pub fn descriptor(&self) -> &PreparedComponent {
        &self.descriptor
    }

    /// Recovers a backend's own guard. A type mismatch returns the intact owner;
    /// dropping that error still reclaims its original guard exactly once.
    pub fn into_parts<T: Any + Send + Sync>(self) -> Result<(PreparedComponent, T), Self> {
        let Self {
            descriptor,
            ownership,
        } = self;
        match ownership.downcast::<T>() {
            Ok(ownership) => Ok((*descriptor, *ownership)),
            Err(ownership) => Err(Self {
                descriptor,
                ownership,
            }),
        }
    }
}

impl fmt::Debug for PreparedUse {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedUse")
            .field("descriptor", &self.descriptor)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    use latent_core::{Metadata, ReleaseDigest};

    use super::*;
    use crate::PreparationKey;

    struct Owner(Arc<AtomicUsize>);
    impl Drop for Owner {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::Relaxed);
        }
    }

    fn descriptor() -> PreparedComponent {
        PreparedComponent {
            key: PreparationKey {
                release: ReleaseDigest("release".to_owned()),
                engine_version: "test".to_owned(),
                engine_configuration_digest: "test".to_owned(),
                target_triple: "test".to_owned(),
                cpu_feature_set: "test".to_owned(),
            },
            backend: "test".to_owned(),
            opaque_handle: "test".to_owned(),
            metadata: Metadata::new(),
        }
    }

    #[test]
    fn ownership_survives_failed_downcast_and_is_released_exactly_once() {
        let drops = Arc::new(AtomicUsize::new(0));
        let prepared = PreparedUse::new(descriptor(), Owner(Arc::clone(&drops)));
        let prepared = prepared
            .into_parts::<()>()
            .expect_err("wrong backend guard");
        assert_eq!(prepared.descriptor(), &descriptor());
        assert_eq!(drops.load(Ordering::Relaxed), 0);
        let (actual, owner) = prepared.into_parts::<Owner>().expect("original owner");
        assert_eq!(actual, descriptor());
        assert_eq!(drops.load(Ordering::Relaxed), 0);
        drop(owner);
        assert_eq!(drops.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn an_unpolled_future_and_unwind_drop_the_original_owner() {
        let drops = Arc::new(AtomicUsize::new(0));
        let prepared = PreparedUse::new(descriptor(), Owner(Arc::clone(&drops)));
        let future = async move {
            std::future::pending::<()>().await;
            drop(prepared);
        };
        drop(future);
        assert_eq!(drops.load(Ordering::Relaxed), 1);
        let prepared = PreparedUse::new(descriptor(), Owner(Arc::clone(&drops)));
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
            let _prepared = prepared;
            panic!("bounded ownership unwind");
        }));
        assert!(result.is_err());
        assert_eq!(drops.load(Ordering::Relaxed), 2);
    }
}
