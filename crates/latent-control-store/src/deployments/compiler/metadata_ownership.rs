//! Test-only observation of the actual compiler metadata owner, not an RSS estimate.
//!
//! The production build does not compile this module. A session is local to the
//! polling thread used by the deterministic fixture. Owners carry their observer
//! through moves and clones, and refund only after their metadata is destroyed.
//! Documentation bytes are an exact payload observation, not total heap accounting.

use std::cell::RefCell;
use std::marker::PhantomData;
use std::ops::Deref;
use std::rc::Rc;
use std::sync::{Arc, Mutex};

use latent_artifacts::VerifiedArtifactMetadata;

thread_local! {
    static ACTIVE: RefCell<Option<Arc<Mutex<Counts>>>> = const { RefCell::new(None) };
}

#[derive(Clone, Copy, Debug, Default)]
pub(in crate::deployments) struct Counts {
    pub fetched: usize,
    pub created: usize,
    pub dropped: usize,
    pub live: usize,
    pub peak_live: usize,
    pub documentation_bytes: usize,
    pub peak_documentation_bytes: usize,
    retain: bool,
}

pub(in crate::deployments) struct Session {
    counts: Arc<Mutex<Counts>>,
    // Installation and removal must happen on the same polling thread.
    _thread: PhantomData<Rc<()>>,
}

impl Session {
    pub fn begin(retain: bool) -> Self {
        let counts = Arc::new(Mutex::new(Counts {
            retain,
            ..Counts::default()
        }));
        ACTIVE.with(|active| {
            let mut active = active.borrow_mut();
            assert!(active.is_none(), "nested metadata observation session");
            *active = Some(Arc::clone(&counts));
        });
        Self {
            counts,
            _thread: PhantomData,
        }
    }

    pub fn snapshot(&self) -> Counts {
        *self.counts.lock().unwrap()
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        ACTIVE.with(|active| {
            active.borrow_mut().take();
        });
    }
}

pub(super) struct ObservedMetadata {
    value: Option<VerifiedArtifactMetadata>,
    counts: Option<Arc<Mutex<Counts>>>,
    documentation_bytes: usize,
}

impl ObservedMetadata {
    pub(super) fn fetched(value: VerifiedArtifactMetadata) -> Self {
        let counts = ACTIVE.with(|active| active.borrow().clone());
        if let Some(counts) = &counts {
            counts.lock().unwrap().fetched += 1;
        }
        Self::owned(value, counts)
    }

    fn owned(value: VerifiedArtifactMetadata, counts: Option<Arc<Mutex<Counts>>>) -> Self {
        let documentation_bytes = if counts.is_some() {
            value
                .contracts()
                .iter()
                .flat_map(|contract| &contract.interfaces)
                .map(|interface| {
                    interface.documentation.as_ref().map_or(0, String::len)
                        + interface
                            .functions
                            .iter()
                            .map(|function| function.documentation.as_ref().map_or(0, String::len))
                            .sum::<usize>()
                })
                .sum()
        } else {
            0
        };
        if let Some(counts) = &counts {
            let mut counts = counts.lock().unwrap();
            counts.created += 1;
            counts.live += 1;
            counts.documentation_bytes += documentation_bytes;
            counts.peak_live = counts.peak_live.max(counts.live);
            counts.peak_documentation_bytes = counts
                .peak_documentation_bytes
                .max(counts.documentation_bytes);
        }
        Self {
            value: Some(value),
            counts,
            documentation_bytes,
        }
    }
}

impl Clone for ObservedMetadata {
    fn clone(&self) -> Self {
        Self::owned(self.deref().clone(), self.counts.clone())
    }
}

impl Deref for ObservedMetadata {
    type Target = VerifiedArtifactMetadata;

    fn deref(&self) -> &Self::Target {
        self.value.as_ref().expect("live metadata owner")
    }
}

impl Drop for ObservedMetadata {
    fn drop(&mut self) {
        // Do not refund a historical arrival or a still-owned payload.
        drop(self.value.take());
        if let Some(counts) = &self.counts {
            let mut counts = counts.lock().unwrap();
            counts.dropped += 1;
            counts.live -= 1;
            counts.documentation_bytes -= self.documentation_bytes;
        }
    }
}

/// The negative control really retains cloned metadata across compiler groups.
/// It is not a synthetic increment of the ownership counters.
#[derive(Default)]
pub(super) struct Retainer(Vec<ObservedMetadata>);

impl Retainer {
    pub(super) fn observe(&mut self, metadata: &ObservedMetadata) {
        let retain = metadata
            .counts
            .as_ref()
            .is_some_and(|counts| counts.lock().unwrap().retain);
        if retain {
            self.0.push(metadata.clone());
        }
    }
}
