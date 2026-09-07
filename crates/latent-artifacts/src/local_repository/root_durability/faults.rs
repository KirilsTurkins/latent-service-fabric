//! Thread-local root synchronization failpoints, absent from production builds.

use std::cell::RefCell;
use std::path::{Path, PathBuf};
use std::rc::Rc;

struct Trace {
    fail: Option<PathBuf>,
    events: Vec<PathBuf>,
}

thread_local! {
    static TRACE: RefCell<Option<Rc<RefCell<Trace>>>> = const { RefCell::new(None) };
}

// Keep each guard on the thread where its failpoint and trace are installed.
pub(in crate::local_repository) struct Guard(Rc<RefCell<Trace>>);

impl Guard {
    pub(in crate::local_repository) fn new(fail: Option<PathBuf>) -> Self {
        let trace = Rc::new(RefCell::new(Trace {
            fail,
            events: Vec::new(),
        }));
        TRACE.with(|slot| {
            let mut slot = slot.borrow_mut();
            assert!(slot.is_none(), "nested artifact root fault guard");
            *slot = Some(Rc::clone(&trace));
        });
        Self(trace)
    }

    pub(in crate::local_repository) fn events(&self) -> Vec<PathBuf> {
        self.0.borrow().events.clone()
    }
}

impl Drop for Guard {
    fn drop(&mut self) {
        TRACE.with(|trace| *trace.borrow_mut() = None);
    }
}

pub(super) fn checkpoint(path: &Path) -> std::io::Result<()> {
    TRACE.with(|slot| {
        if let Some(trace) = slot.borrow().as_ref() {
            let mut trace = trace.borrow_mut();
            trace.events.push(path.to_owned());
            if trace.fail.as_deref() == Some(path) {
                trace.fail = None;
                return Err(std::io::Error::other(
                    "injected artifact root synchronization failure",
                ));
            }
        }
        Ok(())
    })
}
