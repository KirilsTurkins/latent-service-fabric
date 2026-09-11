//! Optional fixed-size operation receipts. Local counters never acquire a lock.

#[cfg(feature = "catalog-observation")]
mod model;
#[cfg(feature = "catalog-observation")]
mod state;
#[cfg(feature = "catalog-observation")]
pub use model::*;
#[cfg(feature = "catalog-observation")]
pub use state::CatalogWorkObserver;

/// One public mutation or explicit catalog compilation; reads do not create receipts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[cfg_attr(
    feature = "catalog-observation",
    derive(latent_manifest::__serde::Serialize)
)]
#[cfg_attr(
    feature = "catalog-observation",
    serde(crate = "latent_manifest::__serde", rename_all = "kebab-case")
)]
pub enum CatalogWorkOperation {
    Open,
    ApplyMany,
    ApplyVersioned,
    DeleteVersioned,
    CompileSnapshot,
    PublishSnapshot,
}

#[derive(Clone, Default)]
pub(super) struct Source {
    #[cfg(feature = "catalog-observation")]
    observer: Option<CatalogWorkObserver>,
}

impl Source {
    #[cfg(feature = "catalog-observation")]
    pub(super) fn observed(observer: CatalogWorkObserver) -> Self {
        Self {
            observer: Some(observer),
        }
    }

    pub(super) fn begin(&self, operation: CatalogWorkOperation) -> Work {
        #[cfg(feature = "catalog-observation")]
        return Work {
            tracked: self
                .observer
                .as_ref()
                .and_then(|observer| observer.begin(operation)),
        };
        #[cfg(not(feature = "catalog-observation"))]
        {
            let _ = operation;
            Work::default()
        }
    }
}

/// This owner outlives the operation's inner future, payloads and lock guards.
#[derive(Default)]
pub(super) struct Work {
    #[cfg(feature = "catalog-observation")]
    tracked: Option<state::Tracked>,
}

impl Work {
    pub(super) fn finish<T, E>(&mut self, result: &Result<T, E>) {
        #[cfg(feature = "catalog-observation")]
        if let Some(tracked) = &mut self.tracked {
            tracked.receipt.outcome = if result.is_ok() {
                CatalogWorkOutcome::ReturnedOk
            } else {
                CatalogWorkOutcome::ReturnedError
            };
        }
        #[cfg(not(feature = "catalog-observation"))]
        let _ = result;
    }

    pub(super) fn generation(&mut self, generation: u64) {
        #[cfg(feature = "catalog-observation")]
        if let Some(tracked) = &mut self.tracked {
            tracked.receipt.compiled_generation = Some(generation);
        }
        #[cfg(not(feature = "catalog-observation"))]
        let _ = generation;
    }

    #[cfg(feature = "catalog-observation")]
    pub(super) fn add(
        &mut self,
        field: impl FnOnce(&mut CatalogWorkCounts) -> &mut u64,
        value: u64,
    ) {
        if let Some(tracked) = &mut self.tracked {
            let target = field(&mut tracked.receipt.counts);
            if let Some(next) = target.checked_add(value) {
                *target = next;
            } else {
                tracked.receipt.overflowed = true;
            }
        }
    }

    #[cfg(feature = "catalog-observation")]
    pub(super) fn maximum(
        &mut self,
        field: impl FnOnce(&mut CatalogWorkCounts) -> &mut u64,
        value: u64,
    ) {
        if let Some(tracked) = &mut self.tracked {
            let target = field(&mut tracked.receipt.counts);
            *target = (*target).max(value);
        }
    }

    pub(super) fn written(&mut self, bytes: Option<usize>) {
        #[cfg(feature = "catalog-observation")]
        if let Some(tracked) = &mut self.tracked {
            let target = &mut tracked.receipt.counts.stage_written_bytes;
            match (*target, bytes) {
                (Some(previous), Some(bytes)) => {
                    if let Some(next) = previous.checked_add(bytes as u64) {
                        *target = Some(next);
                    } else {
                        *target = None;
                        tracked.receipt.overflowed = true;
                    }
                }
                _ => *target = None,
            }
        }
        #[cfg(not(feature = "catalog-observation"))]
        let _ = bytes;
    }
}

macro_rules! count {
    ($work:expr, $field:ident, $value:expr) => {{
        #[cfg(feature = "catalog-observation")]
        $work.add(|counts| &mut counts.$field, $value as u64);
        #[cfg(not(feature = "catalog-observation"))]
        let _ = &$work;
    }};
}
pub(super) use count;

macro_rules! maximum {
    ($work:expr, $field:ident, $value:expr) => {{
        #[cfg(feature = "catalog-observation")]
        $work.maximum(|counts| &mut counts.$field, $value as u64);
        #[cfg(not(feature = "catalog-observation"))]
        let _ = &$work;
    }};
}
pub(super) use maximum;

#[cfg(all(test, not(feature = "catalog-observation")))]
#[test]
fn disabled_feature_has_no_retained_observation_state() {
    assert_eq!(std::mem::size_of::<Source>(), 0);
    assert_eq!(std::mem::size_of::<Work>(), 0);
}
