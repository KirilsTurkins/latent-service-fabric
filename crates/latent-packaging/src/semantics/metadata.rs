//! Resource preflight for the upstream decoder's optional package-docs JSON.
//! Documentation is not part of the trusted structural comparison.
use super::{exhausted, invalid, SemanticLimits};
use latent_core::PlatformError;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use std::fmt;

pub(super) fn validate_package_docs(
    bytes: &[u8],
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    if bytes.len() > limits.max_wit_source_bytes {
        return Err(exhausted("package-docs-byte-limit"));
    }
    if !matches!(bytes.first(), Some(0 | 1)) {
        return Err(invalid("invalid-package-docs-version"));
    }
    let mut state = State {
        limits,
        nodes: 0,
        exceeded: false,
    };
    let mut decoder = serde_json::Deserializer::from_slice(&bytes[1..]);
    let result = Seed {
        state: &mut state,
        depth: 1,
        key: false,
    }
    .deserialize(&mut decoder)
    .and_then(|()| decoder.end());
    result.map_err(|_| {
        if state.exceeded {
            exhausted("package-docs-structure-limit")
        } else {
            invalid("invalid-package-docs-json")
        }
    })
}

struct State {
    limits: SemanticLimits,
    nodes: usize,
    exceeded: bool,
}
impl State {
    fn check<E: de::Error>(&mut self, condition: bool) -> Result<(), E> {
        if condition {
            Ok(())
        } else {
            self.exceeded = true;
            Err(E::custom("package-docs limit"))
        }
    }
}
struct Seed<'a> {
    state: &'a mut State,
    depth: usize,
    key: bool,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, decoder: D) -> Result<(), D::Error> {
        self.state.check(
            self.depth <= self.state.limits.max_type_depth
                && self.state.nodes < self.state.limits.max_type_nodes,
        )?;
        self.state.nodes += 1;
        if self.key {
            decoder.deserialize_str(self)
        } else {
            decoder.deserialize_any(self)
        }
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = ();
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded package-docs JSON")
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<(), E> {
        self.state.check(
            value.len()
                <= if self.key {
                    self.state.limits.max_name_bytes
                } else {
                    self.state.limits.max_wit_source_bytes
                },
        )
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<(), E> {
        self.visit_str(&value)
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
    fn visit_bool<E: de::Error>(self, _: bool) -> Result<(), E> {
        Ok(())
    }
    fn visit_unit<E: de::Error>(self) -> Result<(), E> {
        Ok(())
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<(), A::Error> {
        let mut entries = 0;
        while let Some(()) = seq.next_element_seed(Seed {
            state: self.state,
            depth: self.depth + 1,
            key: false,
        })? {
            entries += 1;
            self.state
                .check(entries <= self.state.limits.max_type_members)?;
        }
        Ok(())
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<(), A::Error> {
        let mut entries = 0;
        while let Some(()) = map.next_key_seed(Seed {
            state: self.state,
            depth: self.depth + 1,
            key: true,
        })? {
            entries += 1;
            self.state
                .check(entries <= self.state.limits.max_type_members)?;
            map.next_value_seed(Seed {
                state: self.state,
                depth: self.depth + 1,
                key: false,
            })?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn package_docs_are_bounded_before_upstream_serde_allocation() {
        let limits = SemanticLimits::default();
        validate_package_docs(b"\x01{\"docs\":\"hello\"}", limits).unwrap();
        assert!(validate_package_docs(b"\x02{}", limits).is_err());
        assert!(validate_package_docs(b"\x01{}{}", limits).is_err());
        assert!(validate_package_docs(
            b"\x01[[[[0]]]]",
            SemanticLimits {
                max_type_depth: 3,
                ..limits
            }
        )
        .is_err());
        assert!(validate_package_docs(
            b"\x01[0,0,0]",
            SemanticLimits {
                max_type_members: 2,
                ..limits
            }
        )
        .is_err());
        assert!(validate_package_docs(
            b"\x01{\"a\":\"b\"}",
            SemanticLimits {
                max_type_nodes: 2,
                ..limits
            }
        )
        .is_err());
    }
}
