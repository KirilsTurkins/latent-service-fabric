//! Duplicate-aware bounded JSON, including policy booleans and receipt nulls.
use latent_core::PlatformError;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use std::{collections::BTreeSet, fmt};

pub(super) fn preflight(bytes: &[u8], maximum: usize) -> Result<(), PlatformError> {
    if bytes.len() > maximum {
        return Err(super::invalid("admission-document-limit"));
    }
    let mut state = State { nodes: 0 };
    let mut decoder = serde_json::Deserializer::from_slice(bytes);
    Seed {
        state: &mut state,
        depth: 1,
    }
    .deserialize(&mut decoder)
    .and_then(|()| decoder.end())
    .map_err(|_| super::invalid("admission-json-profile"))
}
struct State {
    nodes: usize,
}
struct Seed<'a> {
    state: &'a mut State,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, decoder: D) -> Result<(), D::Error> {
        self.state.nodes += 1;
        if self.depth > 16 || self.state.nodes > 16_384 {
            return Err(de::Error::custom("admission JSON limit"));
        }
        decoder.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = ();
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded admission JSON")
    }
    fn visit_bool<E: de::Error>(self, _: bool) -> Result<(), E> {
        Ok(())
    }
    fn visit_unit<E: de::Error>(self) -> Result<(), E> {
        Ok(())
    }
    fn visit_u64<E: de::Error>(self, _: u64) -> Result<(), E> {
        Ok(())
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<(), E> {
        if value.len() > 4096 {
            return Err(E::custom("admission string limit"));
        }
        Ok(())
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut entries: A) -> Result<(), A::Error> {
        let mut count = 0;
        loop {
            if count == 256 {
                entries.next_element_seed(Reject)?;
                return Ok(());
            }
            if entries
                .next_element_seed(Seed {
                    state: self.state,
                    depth: self.depth + 1,
                })?
                .is_none()
            {
                return Ok(());
            }
            count += 1;
        }
    }
    fn visit_map<A: MapAccess<'de>>(self, mut entries: A) -> Result<(), A::Error> {
        let mut keys = BTreeSet::new();
        loop {
            if keys.len() == 32 {
                entries.next_key_seed(Reject)?;
                return Ok(());
            }
            let Some(key) = entries.next_key_seed(Key)? else {
                return Ok(());
            };
            self.state.nodes += 1;
            if self.state.nodes > 16_384 || !keys.insert(key) {
                return Err(de::Error::custom("admission duplicate key or node limit"));
            }
            entries.next_value_seed(Seed {
                state: self.state,
                depth: self.depth + 1,
            })?;
        }
    }
}
struct Key;
impl<'de> DeserializeSeed<'de> for Key {
    type Value = Box<str>;
    fn deserialize<D: de::Deserializer<'de>>(self, decoder: D) -> Result<Self::Value, D::Error> {
        decoder.deserialize_str(self)
    }
}
impl Visitor<'_> for Key {
    type Value = Box<str>;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded admission key")
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<Self::Value, E> {
        if value.len() > 128 {
            return Err(E::custom("admission key limit"));
        }
        Ok(value.into())
    }
}
struct Reject;
impl<'de> DeserializeSeed<'de> for Reject {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, _: D) -> Result<(), D::Error> {
        Err(de::Error::custom("admission collection limit"))
    }
}
