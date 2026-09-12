//! Allocation-free structure retention before decoding the small closed DTO.
use latent_core::PlatformError;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use std::fmt;

pub(super) fn preflight(bytes: &[u8]) -> Result<(), PlatformError> {
    let mut nodes = 0;
    let mut decoder = serde_json::Deserializer::from_slice(bytes);
    Scan {
        depth: 1,
        nodes: &mut nodes,
    }
    .deserialize(&mut decoder)
    .map_err(|_| super::invalid_receipt())?;
    decoder.end().map_err(|_| super::invalid_receipt())
}

struct Scan<'a> {
    depth: usize,
    nodes: &'a mut usize,
}
impl<'de> DeserializeSeed<'de> for Scan<'_> {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, decoder: D) -> Result<(), D::Error> {
        *self.nodes += 1;
        if self.depth > 8 || *self.nodes > 1024 {
            return Err(de::Error::custom("receipt structural limit"));
        }
        decoder.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Scan<'_> {
    type Value = ();
    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("bounded receipt JSON without null values")
    }
    fn visit_bool<E: de::Error>(self, _: bool) -> Result<(), E> {
        Ok(())
    }
    fn visit_u64<E: de::Error>(self, _: u64) -> Result<(), E> {
        Ok(())
    }
    fn visit_i64<E: de::Error>(self, _: i64) -> Result<(), E> {
        Ok(())
    }
    fn visit_f64<E: de::Error>(self, _: f64) -> Result<(), E> {
        Ok(())
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<(), E> {
        if value.len() > 1024 {
            return Err(E::custom("receipt string limit"));
        }
        Ok(())
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut values: A) -> Result<(), A::Error> {
        while values
            .next_element_seed(Scan {
                depth: self.depth + 1,
                nodes: self.nodes,
            })?
            .is_some()
        {}
        Ok(())
    }
    fn visit_map<A: MapAccess<'de>>(self, mut values: A) -> Result<(), A::Error> {
        while values
            .next_key_seed(Scan {
                depth: self.depth + 1,
                nodes: self.nodes,
            })?
            .is_some()
        {
            values.next_value_seed(Scan {
                depth: self.depth + 1,
                nodes: self.nodes,
            })?;
        }
        Ok(())
    }
}
