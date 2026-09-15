//! Closed typed decoding without a JSON value tree. The raw frame and lexical
//! work bounds precede serde, including its escaped-string scratch allocation.
use super::HttpError;
use serde::{
    de::{self, DeserializeSeed, SeqAccess, Visitor},
    Deserialize, Deserializer, Serialize, Serializer,
};
use std::{fmt, marker::PhantomData};

#[derive(Serialize)]
#[serde(transparent)]
pub(super) struct BoundedText<const N: usize>(pub String);

impl<'de, const N: usize> Deserialize<'de> for BoundedText<N> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Text<const N: usize>;
        impl<const N: usize> Visitor<'_> for Text<N> {
            type Value = BoundedText<N>;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("bounded text")
            }
            fn visit_str<E: de::Error>(self, text: &str) -> Result<Self::Value, E> {
                if text.len() > N {
                    return Err(E::custom("text limit"));
                }
                let mut value = String::new();
                value
                    .try_reserve_exact(text.len())
                    .map_err(|_| E::custom("allocation limit"))?;
                value.push_str(text);
                Ok(BoundedText(value))
            }
        }
        deserializer.deserialize_str(Text::<N>)
    }
}

#[derive(Serialize)]
#[serde(transparent)]
pub(super) struct BoundedList<T, const N: usize>(pub Vec<T>);
pub(super) type BoundedBytes<const N: usize> = BoundedList<u8, N>;

/// Reserve before inserting; growth and its transient old allocation are bounded.
pub(super) fn push<T>(values: &mut Vec<T>, value: T, maximum: usize) -> Result<(), HttpError> {
    if values.len() >= maximum {
        return Err(HttpError::BodyTooLarge);
    }
    if values.len() == values.capacity() {
        let next = values.capacity().saturating_mul(2).max(8).min(maximum);
        values
            .try_reserve_exact(next - values.len())
            .map_err(|_| HttpError::AllocationFailed)?;
    }
    values.push(value);
    Ok(())
}

struct Reject;
impl<'de> DeserializeSeed<'de> for Reject {
    type Value = ();
    fn deserialize<D: Deserializer<'de>>(self, _: D) -> Result<(), D::Error> {
        Err(de::Error::custom("collection limit"))
    }
}

impl<'de, T: Deserialize<'de>, const N: usize> Deserialize<'de> for BoundedList<T, N> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct List<T, const N: usize>(PhantomData<T>);
        impl<'de, T: Deserialize<'de>, const N: usize> Visitor<'de> for List<T, N> {
            type Value = BoundedList<T, N>;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("bounded list")
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut input: A) -> Result<Self::Value, A::Error> {
                let mut values = Vec::new();
                while values.len() < N {
                    let Some(value) = input.next_element()? else {
                        return Ok(BoundedList(values));
                    };
                    push(&mut values, value, N).map_err(de::Error::custom)?;
                }
                // Reject an excess element before asking its type to decode it.
                input.next_element_seed(Reject)?;
                Ok(BoundedList(values))
            }
        }
        deserializer.deserialize_seq(List::<T, N>(PhantomData))
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub(super) enum Optional<T> {
    None(()),
    Some(T),
}

impl<T> Optional<T> {
    pub fn as_ref(&self) -> Option<&T> {
        match self {
            Self::None(()) => None,
            Self::Some(value) => Some(value),
        }
    }
    pub fn from_option(value: Option<T>) -> Self {
        value.map_or(Self::None(()), Self::Some)
    }
}

pub(super) struct Decimal(pub u64);
impl Serialize for Decimal {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(&self.0)
    }
}
impl<'de> Deserialize<'de> for Decimal {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = BoundedText::<20>::deserialize(deserializer)?;
        decimal(&value.0)
            .map(Self)
            .ok_or_else(|| de::Error::custom("canonical u64 string required"))
    }
}
pub(super) fn decimal(value: &str) -> Option<u64> {
    if value.is_empty()
        || (value.len() > 1 && value.starts_with('0'))
        || !value.bytes().all(|b| b.is_ascii_digit())
    {
        return None;
    }
    value.parse().ok()
}
