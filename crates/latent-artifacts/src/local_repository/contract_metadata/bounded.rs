use std::fmt;

use latent_core::PlatformError;
use latent_manifest::{
    __serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor},
    __serde::Deserializer,
    __serde_json::{self as serde_json, Map, Number, Value},
};

use super::{exhausted, invalid, ContractMetadataLimits};

pub(super) fn parse(bytes: &[u8], limits: ContractMetadataLimits) -> Result<Value, PlatformError> {
    // Account parser scratch before parsing escaped strings. Input remains borrowed.
    let scratch = bytes
        .len()
        .checked_mul(2)
        .ok_or_else(|| exhausted("contract-metadata-retained-limit"))?;
    if scratch > limits.max_retained_bytes {
        return Err(exhausted("contract-metadata-retained-limit"));
    }
    let mut budget = Budget {
        limits,
        used: scratch,
        nodes: 0,
        failure: None,
    };
    let mut decoder = serde_json::Deserializer::from_slice(bytes);
    let parsed = Seed {
        budget: &mut budget,
        depth: 1,
    }
    .deserialize(&mut decoder);
    let parsed = parsed.and_then(|value| {
        decoder.end()?;
        Ok(value)
    });
    parsed.map_err(|_| budget.failure.map_or_else(invalid, exhausted))
}

struct Budget {
    limits: ContractMetadataLimits,
    used: usize,
    nodes: usize,
    failure: Option<&'static str>,
}
impl Budget {
    fn fail<E: de::Error>(&mut self, reason: &'static str) -> E {
        self.failure = Some(reason);
        E::custom("contract metadata limit")
    }
    fn charge<E: de::Error>(&mut self, bytes: usize) -> Result<(), E> {
        self.used = self
            .used
            .checked_add(bytes)
            .filter(|used| *used <= self.limits.max_retained_bytes)
            .ok_or_else(|| self.fail("contract-metadata-retained-limit"))?;
        Ok(())
    }
    fn node<E: de::Error>(&mut self, depth: usize) -> Result<(), E> {
        if depth > self.limits.max_depth {
            return Err(self.fail("contract-metadata-depth-limit"));
        }
        self.nodes = self
            .nodes
            .checked_add(1)
            .filter(|nodes| *nodes <= self.limits.max_nodes)
            .ok_or_else(|| self.fail("contract-metadata-node-limit"))?;
        // Includes sparse JSON B-tree slots, array capacity, and simultaneously
        // retained storage/domain DTOs during consuming conversion.
        self.charge(1024)
    }
    fn string<E: de::Error>(&mut self, bytes: usize) -> Result<(), E> {
        if bytes > self.limits.max_string_bytes {
            return Err(self.fail("contract-metadata-string-limit"));
        }
        let charged = bytes
            .checked_mul(4)
            .ok_or_else(|| self.fail("contract-metadata-retained-limit"))?;
        self.charge(charged)
    }
}

struct Seed<'a> {
    budget: &'a mut Budget,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = Value;
    fn deserialize<D: Deserializer<'de>>(self, decoder: D) -> Result<Value, D::Error> {
        self.budget.node(self.depth)?;
        decoder.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = Value;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded contract metadata")
    }
    fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }
    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Value, E> {
        Ok(Value::Number(Number::from(value)))
    }
    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(Value::Number(Number::from(value)))
    }
    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Value, E> {
        Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| E::custom("invalid number"))
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<Value, E> {
        self.budget.string(value.len())?;
        Ok(Value::String(value.to_owned()))
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<Value, E> {
        self.budget.string(value.capacity())?;
        Ok(Value::String(value))
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element_seed(Seed {
            budget: self.budget,
            depth: self.depth + 1,
        })? {
            // Each child is charged before growth; cap actual capacity to admitted rows.
            values
                .try_reserve_exact(1)
                .map_err(|_| self.budget.fail("contract-metadata-retained-limit"))?;
            values.push(value);
        }
        Ok(Value::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut values = Map::new();
        while let Some(key) = map.next_key_seed(Key {
            budget: self.budget,
            depth: self.depth + 1,
        })? {
            if values.contains_key(&key) {
                return Err(de::Error::custom("duplicate contract metadata key"));
            }
            let value = map.next_value_seed(Seed {
                budget: self.budget,
                depth: self.depth + 1,
            })?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}

struct Key<'a> {
    budget: &'a mut Budget,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Key<'_> {
    type Value = String;
    fn deserialize<D: Deserializer<'de>>(self, decoder: D) -> Result<String, D::Error> {
        self.budget.node(self.depth)?;
        decoder.deserialize_str(self)
    }
}
impl Visitor<'_> for Key<'_> {
    type Value = String;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded object key")
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<String, E> {
        self.budget.string(value.len())?;
        Ok(value.to_owned())
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<String, E> {
        self.budget.string(value.capacity())?;
        Ok(value)
    }
}
