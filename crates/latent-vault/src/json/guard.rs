use super::{de, DeserializeSeed, MapAccess, Result, SecretError, Visitor, Zeroizing};
use serde::de::SeqAccess;
use std::fmt;

pub(super) fn check(bytes: &[u8]) -> Result<()> {
    let mut nodes = 0;
    let mut decoder = serde_json::Deserializer::from_slice(bytes);
    Seed {
        nodes: &mut nodes,
        depth: 1,
    }
    .deserialize(&mut decoder)
    .and_then(|()| decoder.end())
    .map_err(|_| SecretError::Unavailable)
}
struct Seed<'a> {
    nodes: &'a mut usize,
    depth: usize,
}
impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, d: D) -> std::result::Result<(), D::Error> {
        *self.nodes += 1;
        if *self.nodes > 2048 || self.depth > 8 {
            return Err(de::Error::custom("JSON limit"));
        }
        d.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed<'_> {
    type Value = ();
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded JSON")
    }
    fn visit_bool<E: de::Error>(self, _: bool) -> std::result::Result<(), E> {
        Ok(())
    }
    fn visit_unit<E: de::Error>(self) -> std::result::Result<(), E> {
        Ok(())
    }
    fn visit_u64<E: de::Error>(self, _: u64) -> std::result::Result<(), E> {
        Ok(())
    }
    fn visit_i64<E: de::Error>(self, _: i64) -> std::result::Result<(), E> {
        Ok(())
    }
    fn visit_f64<E: de::Error>(self, _: f64) -> std::result::Result<(), E> {
        Ok(())
    }
    fn visit_str<E: de::Error>(self, value: &str) -> std::result::Result<(), E> {
        if value.len() > 262_144 {
            return Err(E::custom("string limit"));
        }
        Ok(())
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut values: A) -> std::result::Result<(), A::Error> {
        for _ in 0..64 {
            if values
                .next_element_seed(Seed {
                    nodes: self.nodes,
                    depth: self.depth + 1,
                })?
                .is_none()
            {
                return Ok(());
            }
        }
        values.next_element_seed(Reject)?;
        Ok(())
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> std::result::Result<(), A::Error> {
        let mut keys: Vec<Zeroizing<String>> = Vec::new();
        for _ in 0..64 {
            let Some(key) = map.next_key_seed(Key)? else {
                return Ok(());
            };
            if keys.iter().any(|k| **k == *key) {
                return Err(de::Error::custom("duplicate key"));
            }
            keys.push(key);
            map.next_value_seed(Seed {
                nodes: self.nodes,
                depth: self.depth + 1,
            })?;
        }
        map.next_key_seed(Reject)?;
        Ok(())
    }
}
struct Key;
impl<'de> DeserializeSeed<'de> for Key {
    type Value = Zeroizing<String>;
    fn deserialize<D: de::Deserializer<'de>>(
        self,
        d: D,
    ) -> std::result::Result<Self::Value, D::Error> {
        d.deserialize_str(self)
    }
}
impl Visitor<'_> for Key {
    type Value = Zeroizing<String>;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded key")
    }
    fn visit_str<E: de::Error>(self, value: &str) -> std::result::Result<Self::Value, E> {
        if value.len() > 128 {
            return Err(E::custom("key limit"));
        }
        Ok(Zeroizing::new(value.to_owned()))
    }
}
struct Reject;
impl<'de> DeserializeSeed<'de> for Reject {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, _: D) -> std::result::Result<(), D::Error> {
        Err(de::Error::custom("collection limit"))
    }
}
