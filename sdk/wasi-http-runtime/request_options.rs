//! Version-neutral owned request options for a future standard WASI HTTP port.
//!
//! This module exports no WIT family and installs no backend or authority. A
//! future family-specific resource wrapper must keep its own nominal identity.
//! Nondefault timeouts require an explicit typed phase port; none is selected
//! here. Returning an error leaves the previously stored option unchanged.

use super::quota::Slot;
use std::{cell::Cell, marker::PhantomData, rc::Rc};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Unsupported {
    Timeout,
}

pub struct RequestOptions {
    connect: Cell<Option<u64>>,
    first_byte: Cell<Option<u64>>,
    between_bytes: Cell<Option<u64>>,
    slot: Slot,
    local: PhantomData<Rc<()>>,
}

/// Retain the original option slot through the caller's configuration check.
/// This is not a provider owner or a claim of completed physical HTTP work.
#[must_use]
pub struct ConsumedDefaults {
    _slot: Slot,
    _local: PhantomData<Rc<()>>,
}

impl RequestOptions {
    pub fn new() -> Self {
        // The existing shared quota is charged before the generated wrapper
        // boxes this value into its standard resource table.
        let slot = Slot::new();
        Self {
            connect: Cell::new(None),
            first_byte: Cell::new(None),
            between_bytes: Cell::new(None),
            slot,
            local: PhantomData,
        }
    }

    pub fn connect_timeout(&self) -> Option<u64> {
        self.connect.get()
    }

    pub fn first_byte_timeout(&self) -> Option<u64> {
        self.first_byte.get()
    }

    pub fn between_bytes_timeout(&self) -> Option<u64> {
        self.between_bytes.get()
    }

    pub fn set_connect_timeout(&self, value: Option<u64>) -> Result<(), Unsupported> {
        Self::set(&self.connect, value)
    }

    pub fn set_first_byte_timeout(&self, value: Option<u64>) -> Result<(), Unsupported> {
        Self::set(&self.first_byte, value)
    }

    pub fn set_between_bytes_timeout(&self, value: Option<u64>) -> Result<(), Unsupported> {
        Self::set(&self.between_bytes, value)
    }

    fn set(field: &Cell<Option<u64>>, value: Option<u64>) -> Result<(), Unsupported> {
        if value.is_some() {
            return Err(Unsupported::Timeout);
        }
        field.set(None);
        Ok(())
    }

    pub fn consume(self) -> Result<ConsumedDefaults, Unsupported> {
        // Fail closed if a future internal producer introduces a nondefault
        // value without selecting and implementing a typed phase mapping.
        if self.connect.get().is_some()
            || self.first_byte.get().is_some()
            || self.between_bytes.get().is_some()
        {
            return Err(Unsupported::Timeout);
        }
        Ok(ConsumedDefaults {
            _slot: self.slot,
            _local: self.local,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{RequestOptions, Slot, Unsupported};
    use std::panic::catch_unwind;

    #[test]
    fn defaults_and_all_none_setters_are_real_owned_state() {
        let options = RequestOptions::new();
        assert_eq!(options.connect_timeout(), None);
        assert_eq!(options.first_byte_timeout(), None);
        assert_eq!(options.between_bytes_timeout(), None);
        assert_eq!(options.set_connect_timeout(None), Ok(()));
        assert_eq!(options.set_first_byte_timeout(None), Ok(()));
        assert_eq!(options.set_between_bytes_timeout(None), Ok(()));
        let defaults = options.consume().expect("supported default options");
        drop(defaults);
    }

    #[test]
    fn every_nondefault_timeout_refuses_without_changing_state() {
        let options = RequestOptions::new();
        for value in [0, 1, u64::MAX] {
            assert_eq!(
                options.set_connect_timeout(Some(value)),
                Err(Unsupported::Timeout)
            );
            assert_eq!(
                options.set_first_byte_timeout(Some(value)),
                Err(Unsupported::Timeout)
            );
            assert_eq!(
                options.set_between_bytes_timeout(Some(value)),
                Err(Unsupported::Timeout)
            );
            assert_eq!(options.connect_timeout(), None);
            assert_eq!(options.first_byte_timeout(), None);
            assert_eq!(options.between_bytes_timeout(), None);
        }
        let defaults = options
            .consume()
            .expect("refused setters preserve defaults");
        drop(defaults);
    }

    #[test]
    fn options_share_the_original_sixty_four_resource_slots() {
        let owners: Vec<_> = (0..63).map(|_| Slot::new()).collect();
        let options = RequestOptions::new();
        assert!(catch_unwind(Slot::new).is_err());
        drop(options);
        let recovered = Slot::new();
        assert!(catch_unwind(RequestOptions::new).is_err());
        drop(recovered);
        drop(owners);
    }

    #[test]
    fn consuming_defaults_keeps_the_same_slot_until_the_configuration_guard_drops() {
        let owners: Vec<_> = (0..63).map(|_| Slot::new()).collect();
        let defaults = RequestOptions::new()
            .consume()
            .expect("default configuration");
        assert!(catch_unwind(Slot::new).is_err());
        drop(defaults);
        let recovered = RequestOptions::new();
        drop(recovered);
        drop(owners);
    }

    #[test]
    fn an_unmapped_internal_value_refuses_and_releases_its_owned_slot() {
        let owners: Vec<_> = (0..63).map(|_| Slot::new()).collect();
        let options = RequestOptions::new();
        options.first_byte.set(Some(u64::MAX));
        assert!(matches!(options.consume(), Err(Unsupported::Timeout)));
        let recovered = Slot::new();
        drop(recovered);
        drop(owners);
    }

    #[test]
    fn clearing_a_stored_value_is_supported_but_a_refused_set_does_not_overwrite_it() {
        let options = RequestOptions::new();
        options.connect.set(Some(7));
        assert_eq!(
            options.set_connect_timeout(Some(8)),
            Err(Unsupported::Timeout)
        );
        assert_eq!(options.connect_timeout(), Some(7));
        assert_eq!(options.set_connect_timeout(None), Ok(()));
        assert_eq!(options.connect_timeout(), None);
        let defaults = options.consume().expect("cleared default configuration");
        drop(defaults);
    }
}
