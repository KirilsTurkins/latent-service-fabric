//! One-shot publication hooks, absent from production builds.

use std::cell::RefCell;
use std::marker::PhantomData;
use std::path::Path;
use std::rc::Rc;

type Hook = Box<dyn FnOnce(&Path)>;
type MetadataScanHook = Box<dyn FnOnce(&crate::PublicationRef)>;

thread_local! {
    static AFTER_RENAME: RefCell<Option<Hook>> = const { RefCell::new(None) };
    static AFTER_METADATA_SCAN: RefCell<Option<MetadataScanHook>> = const { RefCell::new(None) };
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

pub(in crate::local_repository) struct AfterMetadataScanGuard(PhantomData<Rc<()>>);

impl AfterMetadataScanGuard {
    pub(in crate::local_repository) fn new(
        callback: impl FnOnce(&crate::PublicationRef) + 'static,
    ) -> Self {
        AFTER_METADATA_SCAN.with(|slot| {
            assert!(slot.borrow_mut().replace(Box::new(callback)).is_none());
        });
        Self(PhantomData)
    }
}

impl Drop for AfterMetadataScanGuard {
    fn drop(&mut self) {
        AFTER_METADATA_SCAN.with(|slot| *slot.borrow_mut() = None);
    }
}

pub(in crate::local_repository) fn after_metadata_scan(reference: &crate::PublicationRef) {
    let callback = AFTER_METADATA_SCAN.with(|slot| slot.borrow_mut().take());
    if let Some(callback) = callback {
        callback(reference);
    }
}
