//! Bounded preflight before typed allocation; duplicate members and null fail.
use super::SbomLimits;
use latent_core::PlatformError;
use serde::{
    de::{self, DeserializeOwned, DeserializeSeed, MapAccess, SeqAccess, Visitor},
    Serialize,
};
use std::{
    collections::BTreeSet,
    fmt,
    io::{self, Write},
};

pub(super) fn decode<T: DeserializeOwned>(
    bytes: &[u8],
    limits: SbomLimits,
) -> Result<T, PlatformError> {
    limits.validate()?;
    if bytes.is_empty() || bytes.len() > limits.max_document_bytes {
        return Err(crate::exceeded("sbom-document-limit"));
    }
    let mut budget = Budget {
        nodes: 0,
        exceeded: false,
        limits,
    };
    let mut decoder = serde_json::Deserializer::from_slice(bytes);
    let result = Seed {
        budget: &mut budget,
        depth: 0,
        array_limit: 16,
    }
    .deserialize(&mut decoder)
    .and_then(|()| decoder.end());
    result.map_err(|_| {
        if budget.exceeded {
            crate::exceeded("sbom-json-limit")
        } else {
            crate::invalid("invalid-sbom-json")
        }
    })?;
    serde_json::from_slice(bytes).map_err(|_| crate::invalid("invalid-sbom-json"))
}
struct Budget {
    nodes: usize,
    exceeded: bool,
    limits: SbomLimits,
}
impl Budget {
    fn require<E: de::Error>(&mut self, condition: bool) -> Result<(), E> {
        if !condition {
            self.exceeded = true;
            return Err(E::custom("SBOM JSON bound"));
        }
        Ok(())
    }
    fn node<E: de::Error>(&mut self) -> Result<(), E> {
        self.nodes += 1;
        self.require(self.nodes <= 131_072)
    }
}
struct Seed<'a> {
    budget: &'a mut Budget,
    depth: usize,
    array_limit: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, decoder: D) -> Result<(), D::Error> {
        self.budget.node()?;
        self.budget.require(self.depth <= 12)?;
        decoder.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = ();
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded SBOM JSON")
    }
    fn visit_u64<E: de::Error>(self, _: u64) -> Result<(), E> {
        Ok(())
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<(), E> {
        self.budget
            .require(value.len() <= self.budget.limits.max_string_bytes)
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<(), A::Error> {
        let mut count = 0;
        while sequence
            .next_element_seed(Seed {
                budget: self.budget,
                depth: self.depth + 1,
                array_limit: 16,
            })?
            .is_some()
        {
            count += 1;
            self.budget.require(count <= self.array_limit)?;
        }
        Ok(())
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<(), A::Error> {
        let mut keys = BTreeSet::new();
        while let Some(key) = map.next_key::<String>()? {
            self.budget.node()?;
            self.budget.require(
                key.len() <= self.budget.limits.max_string_bytes.min(64) && keys.len() < 24,
            )?;
            let array_limit = match key.as_str() {
                "components" | "entries" => self.budget.limits.max_entries,
                "hashes" | "licenses" => 1,
                _ => 16,
            };
            if !keys.insert(key) {
                return Err(de::Error::custom("duplicate SBOM member"));
            }
            map.next_value_seed(Seed {
                budget: self.budget,
                depth: self.depth + 1,
                array_limit,
            })?;
        }
        Ok(())
    }
}
pub(super) fn encode<T: Serialize>(value: &T, maximum: usize) -> Result<Vec<u8>, PlatformError> {
    if maximum == 0 || maximum > 1_048_576 {
        return Err(crate::invalid("invalid-sbom-limits"));
    }
    let mut writer = LimitedWriter {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value)
        .map_err(|_| crate::exceeded("sbom-document-limit"))?;
    Ok(writer.bytes)
}
struct LimitedWriter {
    bytes: Vec<u8>,
    maximum: usize,
}
impl Write for LimitedWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let next = self
            .bytes
            .len()
            .checked_add(bytes.len())
            .filter(|value| *value <= self.maximum)
            .ok_or_else(|| io::Error::other("SBOM document limit"))?;
        if next > self.bytes.capacity() {
            let capacity = next
                .max(self.bytes.capacity().saturating_mul(2))
                .min(self.maximum);
            self.bytes
                .try_reserve_exact(capacity - self.bytes.len())
                .map_err(io::Error::other)?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
