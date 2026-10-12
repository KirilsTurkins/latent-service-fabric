//! Refuse nested collection/string amplification before native allocation.

use serde::de::{Error, IgnoredAny, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
use std::fmt;

use super::{InventoryEntry, NamespaceSnapshot, RequiredArtifact, RetainedFormat};

pub(super) fn identity<'de, D: Deserializer<'de>>(decoder: D) -> Result<String, D::Error> {
    crate::namespace::compatibility::decode_identity(decoder)
}

fn sequence<'de, T: Deserialize<'de>, D: Deserializer<'de>, const MAX: usize>(
    decoder: D,
) -> Result<Vec<T>, D::Error> {
    struct Bounded<T, const MAX: usize>(std::marker::PhantomData<T>);
    impl<'de, T: Deserialize<'de>, const MAX: usize> Visitor<'de> for Bounded<T, MAX> {
        type Value = Vec<T>;
        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(formatter, "a sequence of at most {MAX} elements")
        }
        fn visit_seq<A: SeqAccess<'de>>(self, mut input: A) -> Result<Self::Value, A::Error> {
            if input.size_hint().is_some_and(|size| size > MAX) {
                return Err(A::Error::custom("bounded sequence exceeded"));
            }
            let mut values = Vec::with_capacity(input.size_hint().unwrap_or(0).min(MAX));
            while values.len() < MAX {
                let Some(value) = input.next_element()? else {
                    return Ok(values);
                };
                values.push(value);
            }
            if input.next_element::<IgnoredAny>()?.is_some() {
                return Err(A::Error::custom("bounded sequence exceeded"));
            }
            Ok(values)
        }
    }
    decoder.deserialize_seq(Bounded::<T, MAX>(std::marker::PhantomData))
}

pub(super) fn record<'de, D: Deserializer<'de>>(decoder: D) -> Result<Vec<u8>, D::Error> {
    sequence::<_, _, 4096>(decoder)
}
pub(super) fn formats<'de, D: Deserializer<'de>>(
    decoder: D,
) -> Result<Vec<RetainedFormat>, D::Error> {
    sequence::<_, _, 128>(decoder)
}
pub(super) fn artifacts<'de, D: Deserializer<'de>>(
    decoder: D,
) -> Result<Vec<RequiredArtifact>, D::Error> {
    sequence::<_, _, 128>(decoder)
}
pub(super) fn namespaces<'de, D: Deserializer<'de>>(
    decoder: D,
) -> Result<Vec<NamespaceSnapshot>, D::Error> {
    sequence::<_, _, 128>(decoder)
}
pub(super) fn inventory<'de, D: Deserializer<'de>>(
    decoder: D,
) -> Result<Vec<InventoryEntry>, D::Error> {
    sequence::<_, _, 128>(decoder)
}
