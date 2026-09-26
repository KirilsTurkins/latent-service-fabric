//! Reject ambiguous/unbounded JSON and retain only the explicitly selected field.
mod guard;
use super::{Result, SecretError, VaultEncoding, VaultReference};
use base64::Engine;
use serde::{
    de::{self, DeserializeSeed, MapAccess, Visitor},
    Deserialize,
};
use std::{borrow::Cow, fmt};
use zeroize::Zeroizing;

pub(super) struct Decoded {
    pub bytes: Zeroizing<Vec<u8>>,
    pub version: u64,
    pub deletion_millis: Option<u64>,
}
#[derive(Deserialize)]
struct Envelope<'a> {
    #[serde(borrow)]
    data: Option<Data<'a>>,
    #[serde(default, borrow)]
    lease_id: Cow<'a, str>,
    #[serde(default)]
    lease_duration: u64,
    #[serde(default)]
    renewable: bool,
}
#[derive(Deserialize)]
struct Data<'a> {
    #[serde(borrow)]
    data: Option<&'a serde_json::value::RawValue>,
    #[serde(borrow)]
    metadata: Metadata<'a>,
}
#[derive(Deserialize)]
struct Metadata<'a> {
    version: u64,
    destroyed: bool,
    #[serde(borrow)]
    deletion_time: Cow<'a, str>,
}
pub(super) fn decode(bytes: &[u8], reference: &VaultReference, maximum: usize) -> Result<Decoded> {
    if bytes.len() > 262_144 {
        return Err(SecretError::Unavailable);
    }
    guard::check(bytes)?;
    let envelope: Envelope<'_> =
        serde_json::from_slice(bytes).map_err(|_| SecretError::Unavailable)?;
    if !envelope.lease_id.is_empty() || envelope.lease_duration != 0 || envelope.renewable {
        return Err(SecretError::Unavailable);
    }
    let data = envelope.data.ok_or(SecretError::Unavailable)?;
    if data.metadata.destroyed {
        return Err(SecretError::NotFound);
    }
    if data.metadata.version == 0
        || reference
            .version
            .is_some_and(|v| v != data.metadata.version)
    {
        return Err(SecretError::Unavailable);
    }
    let deletion_millis = if data.metadata.deletion_time.is_empty() {
        None
    } else {
        let time = time::OffsetDateTime::parse(
            &data.metadata.deletion_time,
            &time::format_description::well_known::Rfc3339,
        )
        .map_err(|_| SecretError::Unavailable)?;
        Some(
            u64::try_from(time.unix_timestamp_nanos() / 1_000_000)
                .map_err(|_| SecretError::NotFound)?,
        )
    };
    let mut decoder =
        serde_json::Deserializer::from_str(data.data.ok_or(SecretError::Unavailable)?.get());
    let bytes = Field { reference, maximum }
        .deserialize(&mut decoder)
        .and_then(|value| {
            decoder.end()?;
            Ok(value)
        })
        .map_err(|_| SecretError::Unavailable)?
        .ok_or(SecretError::NotFound)?;
    Ok(Decoded {
        bytes,
        version: data.metadata.version,
        deletion_millis,
    })
}

#[cfg(test)]
mod tests;
struct Field<'a> {
    reference: &'a VaultReference,
    maximum: usize,
}
impl<'de> DeserializeSeed<'de> for Field<'_> {
    type Value = Option<Zeroizing<Vec<u8>>>;
    fn deserialize<D: de::Deserializer<'de>>(
        self,
        d: D,
    ) -> std::result::Result<Self::Value, D::Error> {
        d.deserialize_map(self)
    }
}
impl<'de> Visitor<'de> for Field<'_> {
    type Value = Option<Zeroizing<Vec<u8>>>;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("KV fields")
    }
    fn visit_map<A: MapAccess<'de>>(
        self,
        mut map: A,
    ) -> std::result::Result<Self::Value, A::Error> {
        let mut result = None;
        while let Some(key) = map.next_key::<String>()? {
            let key = Zeroizing::new(key);
            if *key == self.reference.field {
                if result.is_some() {
                    return Err(de::Error::custom("duplicate field"));
                }
                result = Some(map.next_value_seed(Value {
                    encoding: self.reference.encoding,
                    maximum: self.maximum,
                })?);
            } else {
                map.next_value::<de::IgnoredAny>()?;
            }
        }
        Ok(result)
    }
}
struct Value {
    encoding: VaultEncoding,
    maximum: usize,
}
impl<'de> DeserializeSeed<'de> for Value {
    type Value = Zeroizing<Vec<u8>>;
    fn deserialize<D: de::Deserializer<'de>>(
        self,
        d: D,
    ) -> std::result::Result<Self::Value, D::Error> {
        d.deserialize_str(self)
    }
}
impl Visitor<'_> for Value {
    type Value = Zeroizing<Vec<u8>>;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded string")
    }
    fn visit_str<E: de::Error>(self, value: &str) -> std::result::Result<Self::Value, E> {
        let mut bytes = Zeroizing::new(Vec::with_capacity(self.maximum));
        match self.encoding {
            VaultEncoding::Utf8 => {
                if value.len() > self.maximum {
                    return Err(E::custom("value limit"));
                }
                bytes.extend_from_slice(value.as_bytes());
            }
            VaultEncoding::Base64 => {
                bytes.resize(self.maximum, 0);
                let size = base64::engine::general_purpose::STANDARD
                    .decode_slice(value, &mut bytes)
                    .map_err(|_| E::custom("value encoding/limit"))?;
                bytes.truncate(size);
            }
        }
        Ok(bytes)
    }
}
