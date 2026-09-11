//! Bounded JSON tree: input bounds precede serde scratch allocation; visitors
//! bound owned nodes, strings and collections before retaining them. Typed
//! conversion consumes this tree rather than cloning it.
use std::fmt;

use latent_core::PlatformError;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};

use super::PackageLimits;

pub(super) fn parse(bytes: &[u8], limits: PackageLimits) -> Result<Value, PlatformError> {
    limits.validate()?;
    if bytes.len() > limits.max_document_bytes {
        return Err(super::exceeded("package-document-limit"));
    }
    let mut state = State {
        limits,
        nodes: 0,
        exceeded: false,
    };
    let mut decoder = serde_json::Deserializer::from_slice(bytes);
    let value = Seed {
        state: &mut state,
        depth: 1,
    }
    .deserialize(&mut decoder);
    let result = value.and_then(|value| decoder.end().map(|()| value));
    result.map_err(|_| {
        if state.exceeded {
            super::exceeded("package-json-limit")
        } else {
            super::invalid("invalid-package-json")
        }
    })
}

struct State {
    limits: PackageLimits,
    nodes: usize,
    exceeded: bool,
}
impl State {
    fn check<E: de::Error>(&mut self, allowed: bool) -> Result<(), E> {
        if !allowed {
            self.exceeded = true;
            return Err(E::custom("package JSON limit"));
        }
        Ok(())
    }
    fn node<E: de::Error>(&mut self, depth: usize) -> Result<(), E> {
        self.check(depth <= self.limits.max_depth && self.nodes < self.limits.max_nodes)?;
        self.nodes += 1;
        Ok(())
    }
    fn string<E: de::Error>(&mut self, value: &str) -> Result<(), E> {
        self.check(value.len() <= self.limits.max_string_bytes)
    }
}

struct Seed<'a> {
    state: &'a mut State,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = Value;
    fn deserialize<D: de::Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        self.state.node(self.depth)?;
        deserializer.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = Value;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a bounded package object, array, string or unsigned integer")
    }
    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(value.into())
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<Value, E> {
        self.state.string(value)?;
        Ok(Value::String(value.to_owned()))
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<Value, E> {
        self.state.string(&value)?;
        Ok(Value::String(value))
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        loop {
            // Peek via a rejecting seed at capacity: do not allocate the excess item.
            if values.len() == self.state.limits.max_layers {
                let _ = seq.next_element_seed(Reject { state: self.state })?;
                break;
            }
            match seq.next_element_seed(Seed {
                state: self.state,
                depth: self.depth + 1,
            })? {
                Some(value) => values.push(value),
                None => break,
            }
        }
        Ok(Value::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut values = Map::new();
        while let Some(key) = map.next_key_seed(Key {
            state: self.state,
            depth: self.depth + 1,
        })? {
            self.state
                .check(values.len() < self.state.limits.max_annotations.max(16))?;
            if values.contains_key(&key) {
                return Err(de::Error::custom("duplicate package key"));
            }
            let value = map.next_value_seed(Seed {
                state: self.state,
                depth: self.depth + 1,
            })?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}

struct Key<'a> {
    state: &'a mut State,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Key<'_> {
    type Value = String;
    fn deserialize<D: de::Deserializer<'de>>(self, deserializer: D) -> Result<String, D::Error> {
        self.state.node(self.depth)?;
        deserializer.deserialize_str(self)
    }
}
impl Visitor<'_> for Key<'_> {
    type Value = String;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded object key")
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<String, E> {
        self.state.string(value)?;
        Ok(value.to_owned())
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<String, E> {
        self.state.string(&value)?;
        Ok(value)
    }
}

struct Reject<'a> {
    state: &'a mut State,
}
impl<'de> DeserializeSeed<'de> for Reject<'_> {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, _: D) -> Result<(), D::Error> {
        self.state.exceeded = true;
        Err(de::Error::custom("package collection limit"))
    }
}
