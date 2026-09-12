//! Boolean-bearing bounded JSON; immutable package JSON semantics stay unchanged.
use crate::{SignatureFailure, SignatureResult};
use serde::{
    de::{self, DeserializeOwned, DeserializeSeed, MapAccess, SeqAccess, Visitor},
    Serialize,
};
use std::{
    collections::BTreeSet,
    fmt,
    io::{self, Write},
};

pub(crate) fn decode<T: DeserializeOwned>(
    bytes: &[u8],
    maximum: usize,
    max_array: usize,
) -> SignatureResult<T> {
    preflight(bytes, maximum, max_array, 1024)?;
    serde_json::from_slice(bytes).map_err(|_| SignatureFailure::MalformedProvenance.into())
}
pub(crate) fn preflight(
    bytes: &[u8],
    maximum: usize,
    max_array: usize,
    max_string: usize,
) -> SignatureResult<()> {
    if maximum == 0
        || maximum > 65_536
        || max_array == 0
        || max_array > 256
        || max_string == 0
        || max_string > 65_536
    {
        return Err(SignatureFailure::InvalidLimits.into());
    }
    if bytes.len() > maximum {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    let mut budget = Budget {
        nodes: 0,
        exceeded: false,
        max_array,
        max_string,
    };
    let mut decoder = serde_json::Deserializer::from_slice(bytes);
    let result = Seed {
        budget: &mut budget,
        depth: 0,
    }
    .deserialize(&mut decoder)
    .and_then(|()| decoder.end());
    result.map_err(|_| {
        if budget.exceeded {
            SignatureFailure::ResourceLimit
        } else {
            SignatureFailure::MalformedProvenance
        }
        .into()
    })
}
struct Budget {
    nodes: usize,
    exceeded: bool,
    max_array: usize,
    max_string: usize,
}
impl Budget {
    fn require<E: de::Error>(&mut self, condition: bool) -> Result<(), E> {
        if !condition {
            self.exceeded = true;
            return Err(E::custom("provenance JSON bound"));
        }
        Ok(())
    }
    fn node<E: de::Error>(&mut self) -> Result<(), E> {
        self.nodes += 1;
        self.require(self.nodes <= 4096)
    }
}
struct Seed<'a> {
    budget: &'a mut Budget,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, decoder: D) -> Result<(), D::Error> {
        self.budget.node()?;
        self.budget.require(self.depth <= 16)?;
        decoder.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = ();
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded provenance JSON")
    }
    fn visit_bool<E: de::Error>(self, _: bool) -> Result<(), E> {
        Ok(())
    }
    fn visit_u64<E: de::Error>(self, _: u64) -> Result<(), E> {
        Ok(())
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<(), E> {
        self.budget.require(value.len() <= self.budget.max_string)
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<(), A::Error> {
        let mut count = 0;
        // One excess element can be visited under the global bounds; no value
        // tree is retained. Typed arrays remain bounded before materialization.
        while sequence
            .next_element_seed(Seed {
                budget: self.budget,
                depth: self.depth + 1,
            })?
            .is_some()
        {
            count += 1;
            self.budget.require(count <= self.budget.max_array)?;
        }
        Ok(())
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<(), A::Error> {
        let mut keys = BTreeSet::new();
        while let Some(key) = map.next_key::<String>()? {
            self.budget.node()?;
            self.budget
                .require(key.len() <= self.budget.max_string && keys.len() < 256)?;
            if !keys.insert(key) {
                return Err(de::Error::custom("duplicate provenance member"));
            }
            map.next_value_seed(Seed {
                budget: self.budget,
                depth: self.depth + 1,
            })?;
        }
        Ok(())
    }
}
pub(crate) fn encode<T: Serialize>(value: &T, maximum: usize) -> SignatureResult<Vec<u8>> {
    if maximum == 0 || maximum > 65_536 {
        return Err(SignatureFailure::InvalidLimits.into());
    }
    let mut writer = LimitedWriter {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| SignatureFailure::ResourceLimit)?;
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
            .filter(|n| *n <= self.maximum)
            .ok_or_else(|| io::Error::other("provenance document bound"))?;
        if next > self.bytes.capacity() {
            self.bytes
                .try_reserve_exact(next - self.bytes.len())
                .map_err(io::Error::other)?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
