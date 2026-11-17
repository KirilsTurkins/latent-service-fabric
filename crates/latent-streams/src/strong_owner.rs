//! Private strong-only custody for original physical allocation charges.
use std::{ops::Deref, sync::Arc};

// No raw Arc or Weak escapes this wrapper. Every clone takes the same path,
// so exactly one final drop receives the value after its Arc backing is freed.
pub(crate) struct StrongOwner<T>(Option<Arc<T>>);

impl<T> StrongOwner<T> {
    pub(crate) fn new(value: T) -> Self {
        Self(Some(Arc::new(value)))
    }

    #[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
    pub(crate) fn strong_count(&self) -> usize {
        Arc::strong_count(self.0.as_ref().expect("live strong owner"))
    }
}

impl<T> Clone for StrongOwner<T> {
    fn clone(&self) -> Self {
        Self(Some(Arc::clone(
            self.0.as_ref().expect("live strong owner"),
        )))
    }
}

impl<T> Deref for StrongOwner<T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        self.0.as_deref().expect("live strong owner")
    }
}

impl<T> Drop for StrongOwner<T> {
    fn drop(&mut self) {
        if let Some(owner) = self.0.take() {
            drop(Arc::into_inner(owner));
        }
    }
}
