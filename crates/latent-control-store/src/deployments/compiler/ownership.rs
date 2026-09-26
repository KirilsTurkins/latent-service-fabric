//! Test-only ownership observations, not allocator/RSS or resource qualification.
//!
//! The wrapper owns the actual value, so moving it into a collection keeps its
//! bytes live. Drop is recorded only after destroying that value. Fault injection
//! retains the actual value at drop (not a guessed byte counter or an extra copy).
//! A session is thread-local because these fixtures poll the production futures
//! with the synchronous test executor. It never observes unrelated parallel tests.

use std::any::Any;
use std::cell::RefCell;
use std::marker::PhantomData;
use std::ops::Deref;
use std::rc::Rc;
use std::sync::{Arc, Mutex};

use latent_artifacts::VerifiedArtifactMetadata;
use latent_manifest::__serde_json as json;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(in crate::deployments) enum Kind {
    Release,
    Canonical,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(in crate::deployments) enum Fault {
    None,
    Retain(Kind),
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(in crate::deployments) struct Counter {
    pub acquired: usize,
    pub dropped: usize,
    pub live_bytes: usize,
    pub peak_bytes: usize,
}

struct State {
    counters: [Counter; 2],
    fault: Fault,
    retained: Vec<Box<dyn Any + Send>>,
}

thread_local! {
    static ACTIVE: RefCell<Option<Arc<Mutex<State>>>> = const { RefCell::new(None) };
}

pub(in crate::deployments) struct Session {
    state: Arc<Mutex<State>>,
    // Installing and removing a thread-local session must occur on one thread.
    _thread: PhantomData<Rc<()>>,
}

impl Session {
    pub fn start(fault: Fault) -> Self {
        let state = Arc::new(Mutex::new(State {
            counters: [Counter::default(); 2],
            fault,
            retained: Vec::new(),
        }));
        ACTIVE.with(|active| {
            assert!(active.borrow().is_none(), "nested ownership observation");
            *active.borrow_mut() = Some(Arc::clone(&state));
        });
        Self {
            state,
            _thread: PhantomData,
        }
    }

    pub fn counters(&self) -> [Counter; 2] {
        self.state.lock().unwrap().counters
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        ACTIVE.with(|active| {
            active.borrow_mut().take();
        });
        // Retained fault values are released with State, without a reference cycle.
    }
}

pub(in crate::deployments) struct Owned<T: Send + 'static> {
    value: Option<T>,
    observation: Option<Arc<Mutex<State>>>,
    kind: Kind,
    bytes: usize,
}

impl<T: Send + 'static> Owned<T> {
    fn new(value: T, kind: Kind, bytes: usize) -> Self {
        let observation = ACTIVE.with(|active| active.borrow().clone());
        if let Some(observation) = &observation {
            let mut state = observation.lock().unwrap();
            let counter = &mut state.counters[kind as usize];
            counter.acquired += 1;
            counter.live_bytes += bytes;
            counter.peak_bytes = counter.peak_bytes.max(counter.live_bytes);
        }
        Self {
            value: Some(value),
            observation,
            kind,
            bytes,
        }
    }
}

impl<T: Send + 'static> Deref for Owned<T> {
    type Target = T;

    fn deref(&self) -> &T {
        self.value.as_ref().expect("owned until drop")
    }
}

impl<T: Clone + Send + 'static> Clone for Owned<T> {
    fn clone(&self) -> Self {
        Self::new((**self).clone(), self.kind, self.bytes)
    }
}

impl<T: Send + 'static> Drop for Owned<T> {
    fn drop(&mut self) {
        let value = self.value.take().expect("drop once");
        let Some(observation) = &self.observation else {
            drop(value);
            return;
        };
        let mut state = observation.lock().unwrap();
        if state.fault == Fault::Retain(self.kind) {
            state.retained.push(Box::new(value));
        } else {
            drop(value);
            let counter = &mut state.counters[self.kind as usize];
            counter.live_bytes -= self.bytes;
            counter.dropped += 1;
        }
    }
}

fn text_bytes(value: &Option<String>) -> usize {
    value.as_ref().map_or(0, String::len)
}

pub(in crate::deployments) fn metadata(
    value: VerifiedArtifactMetadata,
) -> Owned<VerifiedArtifactMetadata> {
    let bytes = value
        .contracts()
        .iter()
        .flat_map(|contract| &contract.interfaces)
        .map(|interface| {
            text_bytes(&interface.documentation)
                + interface
                    .functions
                    .iter()
                    .map(|function| {
                        text_bytes(&function.documentation)
                            + function
                                .parameters
                                .iter()
                                .chain(&function.results)
                                .map(|field| text_bytes(&field.documentation))
                                .sum::<usize>()
                    })
                    .sum::<usize>()
        })
        .sum();
    Owned::new(value, Kind::Release, bytes)
}

fn canonical_documentation_bytes(value: &json::Value) -> usize {
    match value {
        json::Value::Object(fields) => fields
            .iter()
            .map(|(key, value)| {
                if key == "documentation" {
                    value.as_str().map_or(0, str::len)
                } else {
                    canonical_documentation_bytes(value)
                }
            })
            .sum(),
        json::Value::Array(values) => values.iter().map(canonical_documentation_bytes).sum(),
        _ => 0,
    }
}

pub(in crate::deployments) fn canonical(value: json::Value) -> Owned<json::Value> {
    let bytes = canonical_documentation_bytes(&value);
    Owned::new(value, Kind::Canonical, bytes)
}
