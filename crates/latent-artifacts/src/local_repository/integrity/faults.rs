//! One-shot publication hooks, absent from production builds.

use std::cell::RefCell;
use std::marker::PhantomData;
use std::path::Path;
use std::rc::Rc;

type Hook = Box<dyn FnOnce(&Path)>;

thread_local! {
    static AFTER_RENAME: RefCell<Option<Hook>> = const { RefCell::new(None) };
}

// A guard cannot leave the thread where its callback is installed.
pub(in crate::local_repository) struct AfterRenameGuard(PhantomData<Rc<()>>);

impl AfterRenameGuard {
    pub(in crate::local_repository) fn new(callback: impl FnOnce(&Path) + 'static) -> Self {
        AFTER_RENAME.with(|slot| {
            let mut slot = slot.borrow_mut();
            assert!(slot.is_none(), "nested publication rename hook");
            *slot = Some(Box::new(callback));
        });
        Self(PhantomData)
    }
}

impl Drop for AfterRenameGuard {
    fn drop(&mut self) {
        AFTER_RENAME.with(|slot| *slot.borrow_mut() = None);
    }
}

pub(in crate::local_repository) fn after_rename(path: &Path) {
    let callback = AFTER_RENAME.with(|slot| slot.borrow_mut().take());
    if let Some(callback) = callback {
        callback(path);
    }
}
