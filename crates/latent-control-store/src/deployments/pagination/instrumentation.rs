//! Test-only per-thread selection and clone accounting.

use std::cell::RefCell;
use std::rc::Rc;

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub(in crate::deployments) struct PageStats {
    pub selected: usize,
    pub cloned: usize,
}

thread_local! {
    static ACTIVE: RefCell<Option<Rc<RefCell<PageStats>>>> = const { RefCell::new(None) };
}

// Rc keeps the guard on the same thread as its counters.
pub(in crate::deployments) struct PageProbe(Rc<RefCell<PageStats>>);

impl PageProbe {
    pub(in crate::deployments) fn new() -> Self {
        let stats = Rc::new(RefCell::new(PageStats::default()));
        ACTIVE.with(|slot| {
            let mut slot = slot.borrow_mut();
            assert!(slot.is_none(), "nested page accounting probe");
            *slot = Some(Rc::clone(&stats));
        });
        Self(stats)
    }

    pub(in crate::deployments) fn stats(&self) -> PageStats {
        *self.0.borrow()
    }
}

impl Drop for PageProbe {
    fn drop(&mut self) {
        ACTIVE.with(|slot| *slot.borrow_mut() = None);
    }
}

pub(super) fn selected() {
    ACTIVE.with(|slot| {
        if let Some(stats) = slot.borrow().as_ref() {
            stats.borrow_mut().selected += 1;
        }
    });
}

pub(super) fn cloned() {
    ACTIVE.with(|slot| {
        if let Some(stats) = slot.borrow().as_ref() {
            stats.borrow_mut().cloned += 1;
        }
    });
}
