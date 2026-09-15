//! An explicit base64 WIT string, never a different meaning for list<u8>.
//! The HTTP transport and retained native body use raw bytes.
use super::{bounded::BoundedText, MAX_RESPONSE_BODY};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{de, Deserialize, Deserializer, Serialize, Serializer};

pub(super) struct Body<const N: usize>(pub Vec<u8>);
impl<const N: usize> Serialize for Body<N> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&STANDARD.encode(&self.0))
    }
}
impl<'de, const N: usize> Deserialize<'de> for Body<N> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        const MAX_ENCODED: usize = MAX_RESPONSE_BODY.div_ceil(3) * 4;
        let text = BoundedText::<MAX_ENCODED>::deserialize(deserializer)?;
        let value = text.0.as_bytes();
        if !value.len().is_multiple_of(4) {
            return Err(de::Error::custom("base64 padding"));
        }
        let padding = value.iter().rev().take_while(|b| **b == b'=').count();
        if padding > 2 {
            return Err(de::Error::custom("base64 padding"));
        }
        let size = (value.len() / 4 * 3)
            .checked_sub(padding)
            .filter(|size| *size <= N)
            .ok_or_else(|| de::Error::custom("body limit"))?;
        // Bound decoded bytes before allocating them. STANDARD requires canonical
        // padding and zero trailing bits and rejects whitespace/non-alphabet bytes.
        let mut bytes = Vec::new();
        bytes
            .try_reserve_exact(size)
            .map_err(|_| de::Error::custom("body allocation"))?;
        bytes.resize(size, 0);
        let actual = STANDARD
            .decode_slice(value, &mut bytes)
            .map_err(|_| de::Error::custom("base64 encoding"))?;
        if actual != size {
            return Err(de::Error::custom("body length"));
        }
        Ok(Self(bytes))
    }
}
