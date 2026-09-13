use super::Failure;
use std::{cell::Cell, rc::Rc};

/// CLI copy accounting is independent of the registry's retained byte leases.
pub(super) struct Budget(Rc<Cell<usize>>);
pub(super) struct Charge {
    remaining: Rc<Cell<usize>>,
    bytes: usize,
}
pub(super) struct Owned<T> {
    pub value: T,
    charge: Charge,
}
impl Budget {
    pub fn new(bytes: usize) -> Self {
        Self(Rc::new(Cell::new(bytes)))
    }
    pub fn reserve(&self, bytes: usize) -> Result<Charge, Failure> {
        let remaining = self.0.get().checked_sub(bytes).ok_or_else(super::limit)?;
        self.0.set(remaining);
        Ok(Charge {
            remaining: Rc::clone(&self.0),
            bytes,
        })
    }
}
impl Charge {
    pub fn own<T>(self, value: T) -> Owned<T> {
        Owned {
            value,
            charge: self,
        }
    }
}
impl<T> Owned<T> {
    pub fn into_parts(self) -> (T, Charge) {
        (self.value, self.charge)
    }
}
impl Drop for Charge {
    fn drop(&mut self) {
        self.remaining.set(self.remaining.get() + self.bytes);
    }
}
