use std::fmt;

use latent_core::PlatformError;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};

use super::{invalid_input, limit, ValueCodecLimits};

const COLLECTION_LIMIT: &str = "value collection limit";

pub(super) fn parse(bytes: &[u8], limits: ValueCodecLimits) -> Result<Value, PlatformError> {
    preflight(bytes, limits)?;
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let value = Seed { limits }
        .deserialize(&mut deserializer)
        .map_err(|error| parse_error(&error))?;
    deserializer.end().map_err(|error| parse_error(&error))?;
    Ok(value)
}

fn parse_error(error: &serde_json::Error) -> PlatformError {
    if error.to_string().contains(COLLECTION_LIMIT) {
        limit()
    } else {
        invalid_input()
    }
}

/// Lexical accounting runs before serde can allocate escaped-string scratch or
/// recursively construct containers. Grammar and duplicate checking follow below.
pub(super) fn preflight(bytes: &[u8], limits: ValueCodecLimits) -> Result<(), PlatformError> {
    if bytes.len() > limits.max_input_bytes {
        return Err(limit());
    }
    std::str::from_utf8(bytes).map_err(|_| invalid_input())?;
    let mut index = 0;
    let mut depth = 0_usize;
    let mut nodes = 0_usize;
    while index < bytes.len() {
        match bytes[index] {
            b' ' | b'\t' | b'\n' | b'\r' | b':' | b',' => index += 1,
            b'[' | b'{' => {
                depth += 1;
                nodes += 1;
                if depth > limits.max_depth {
                    return Err(limit());
                }
                index += 1;
            }
            b']' | b'}' => {
                depth = depth.checked_sub(1).ok_or_else(invalid_input)?;
                index += 1;
            }
            b'"' => {
                nodes += 1;
                scan_string(bytes, &mut index, limits.max_string_bytes)?;
            }
            _ => {
                nodes += 1;
                let start = index;
                while index < bytes.len()
                    && !matches!(
                        bytes[index],
                        b' ' | b'\t'
                            | b'\n'
                            | b'\r'
                            | b','
                            | b':'
                            | b'['
                            | b']'
                            | b'{'
                            | b'}'
                            | b'"'
                    )
                {
                    index += 1;
                }
                // WIT floats use strings, so every bare number must have
                // integer syntax. This also lets serde's special -0 float
                // representation normalize safely to the integer zero.
                if matches!(bytes[start], b'-' | b'0'..=b'9')
                    && bytes[start..index]
                        .iter()
                        .any(|byte| matches!(byte, b'.' | b'e' | b'E'))
                {
                    return Err(invalid_input());
                }
            }
        }
        if nodes > limits.max_nodes {
            return Err(limit());
        }
    }
    if depth != 0 {
        return Err(invalid_input());
    }
    Ok(())
}

fn scan_string(bytes: &[u8], index: &mut usize, maximum: usize) -> Result<(), PlatformError> {
    *index += 1;
    let mut decoded = 0_usize;
    loop {
        let byte = *bytes.get(*index).ok_or_else(invalid_input)?;
        *index += 1;
        match byte {
            b'"' => return Ok(()),
            0..=31 => return Err(invalid_input()),
            b'\\' => {
                let escaped = *bytes.get(*index).ok_or_else(invalid_input)?;
                *index += 1;
                decoded += match escaped {
                    b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't' => 1,
                    b'u' => {
                        let first = unicode_escape(bytes, index)?;
                        let scalar = if (0xd800..=0xdbff).contains(&first) {
                            if bytes.get(*index..*index + 2) != Some(b"\\u") {
                                return Err(invalid_input());
                            }
                            *index += 2;
                            let second = unicode_escape(bytes, index)?;
                            if !(0xdc00..=0xdfff).contains(&second) {
                                return Err(invalid_input());
                            }
                            0x10000 + ((first - 0xd800) << 10) + (second - 0xdc00)
                        } else {
                            first
                        };
                        char::from_u32(scalar).ok_or_else(invalid_input)?.len_utf8()
                    }
                    _ => return Err(invalid_input()),
                };
            }
            _ => decoded += 1, // Input was already validated as UTF-8.
        }
        if decoded > maximum {
            return Err(limit());
        }
    }
}

fn unicode_escape(bytes: &[u8], index: &mut usize) -> Result<u32, PlatformError> {
    let digits = bytes.get(*index..*index + 4).ok_or_else(invalid_input)?;
    let mut scalar = 0_u32;
    for byte in digits {
        scalar = scalar * 16 + char::from(*byte).to_digit(16).ok_or_else(invalid_input)?;
    }
    *index += 4;
    Ok(scalar)
}

#[derive(Clone, Copy)]
struct Seed {
    limits: ValueCodecLimits,
}

impl<'de> DeserializeSeed<'de> for Seed {
    type Value = Value;
    fn deserialize<D: de::Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        deserializer.deserialize_any(ValueVisitor {
            limits: self.limits,
        })
    }
}

struct ValueVisitor {
    limits: ValueCodecLimits,
}

impl<'de> Visitor<'de> for ValueVisitor {
    type Value = Value;
    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("bounded JSON values")
    }
    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }
    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Value, E> {
        Ok(Value::Number(value.into()))
    }
    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(Value::Number(value.into()))
    }
    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Value, E> {
        if value == 0.0 && value.is_sign_negative() {
            return Ok(Value::Number(0.into()));
        }
        Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| E::custom("invalid number"))
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_owned()))
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<Value, E> {
        Ok(Value::String(value))
    }
    fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        loop {
            if values.len() == self.limits.max_collection_items {
                if sequence.next_element_seed(RejectExtra)?.is_some() {
                    unreachable!();
                }
                break;
            }
            let Some(value) = sequence.next_element_seed(Seed {
                limits: self.limits,
            })?
            else {
                break;
            };
            values.push(value);
        }
        Ok(Value::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut object: A) -> Result<Value, A::Error> {
        let mut values = Map::new();
        loop {
            if values.len() == self.limits.max_collection_items {
                if object.next_key_seed(RejectExtra)?.is_some() {
                    unreachable!();
                }
                break;
            }
            let Some(key) = object.next_key::<String>()? else {
                break;
            };
            if values.contains_key(&key) {
                return Err(de::Error::custom("duplicate object key"));
            }
            let value = object.next_value_seed(Seed {
                limits: self.limits,
            })?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}

struct RejectExtra;
impl<'de> DeserializeSeed<'de> for RejectExtra {
    type Value = ();
    fn deserialize<D: de::Deserializer<'de>>(self, _deserializer: D) -> Result<(), D::Error> {
        Err(de::Error::custom(COLLECTION_LIMIT))
    }
}
