use std::fmt;

use serde::de::{self, DeserializeSeed, IgnoredAny, MapAccess, SeqAccess, Visitor};
use serde::Deserialize;

use crate::json_number::representable_integer_lexeme;
use crate::wire_codec::{
    JsonManifestCodec as WireJsonManifestCodec, ManifestLimits as WireManifestLimits,
};
use crate::{
    BindingManifest, CapsuleManifest, DeploymentManifest, ManifestCodec, ManifestDocument,
    ManifestResult, ManifestViolation, PolicyManifest, TriggerManifest,
};

const DEFAULT_MAX_DOCUMENT_BYTES: usize = 1024 * 1024;
const DEFAULT_MAX_NESTING_DEPTH: usize = 64;
const DEFAULT_MAX_STRING_BYTES: usize = 256 * 1024;
const DEFAULT_MAX_COLLECTION_ENTRIES: usize = 4096;
const DEFAULT_MAX_VIOLATIONS: usize = 128;
const COLLECTION_LIMIT_MARKER: &str = "manifest collection entry limit exceeded";

/// Resource-consumption limits applied before and during JSON decoding.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ManifestLimits {
    pub max_document_bytes: usize,
    pub max_nesting_depth: usize,
    pub max_string_bytes: usize,
    /// Maximum number of entries in any one JSON array or object. The check is
    /// performed by a no-allocation preflight visitor before typed values are
    /// constructed.
    pub max_collection_entries: usize,
    pub max_violations: usize,
}

impl Default for ManifestLimits {
    fn default() -> Self {
        Self {
            max_document_bytes: DEFAULT_MAX_DOCUMENT_BYTES,
            max_nesting_depth: DEFAULT_MAX_NESTING_DEPTH,
            max_string_bytes: DEFAULT_MAX_STRING_BYTES,
            max_collection_entries: DEFAULT_MAX_COLLECTION_ENTRIES,
            max_violations: DEFAULT_MAX_VIOLATIONS,
        }
    }
}

/// Bounded public JSON codec. The inner wire codec owns canonical model
/// mapping; this layer enforces admission limits and Draft-compatible integral
/// number normalization before that mapping allocates collections.
#[derive(Debug, Clone)]
pub struct JsonManifestCodec {
    limits: ManifestLimits,
}

impl Default for JsonManifestCodec {
    fn default() -> Self {
        Self::new(ManifestLimits::default())
    }
}

impl JsonManifestCodec {
    #[must_use]
    pub const fn new(limits: ManifestLimits) -> Self {
        Self { limits }
    }

    #[must_use]
    pub const fn limits(&self) -> ManifestLimits {
        self.limits
    }

    /// Decodes any manifest kind identified by its top-level `kind` field.
    pub fn decode_document(&self, bytes: &[u8]) -> ManifestResult<ManifestDocument> {
        let normalized = self.preflight_decode(bytes)?;
        self.wire_codec().decode_document(&normalized)
    }

    /// Canonically encodes a type-erased manifest.
    pub fn encode_document(&self, manifest: &ManifestDocument) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_document(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn wire_codec(&self) -> WireJsonManifestCodec {
        WireJsonManifestCodec::new(WireManifestLimits {
            max_document_bytes: self.limits.max_document_bytes,
            max_nesting_depth: self.limits.max_nesting_depth,
            max_string_bytes: self.limits.max_string_bytes,
            max_violations: self.limits.max_violations,
        })
    }

    fn preflight_decode(&self, bytes: &[u8]) -> ManifestResult<Vec<u8>> {
        enforce_raw_limits(bytes, self.limits)?;
        enforce_collection_limit(bytes, self.limits.max_collection_entries)?;
        Ok(normalize_integral_number_lexemes(bytes))
    }

    fn preflight_encoded(&self, bytes: &[u8]) -> ManifestResult<()> {
        enforce_raw_limits(bytes, self.limits)?;
        enforce_collection_limit(bytes, self.limits.max_collection_entries)
    }
}

impl ManifestCodec for JsonManifestCodec {
    fn decode_capsule(&self, bytes: &[u8]) -> ManifestResult<CapsuleManifest> {
        let normalized = self.preflight_decode(bytes)?;
        self.wire_codec().decode_capsule(&normalized)
    }

    fn encode_capsule(&self, manifest: &CapsuleManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_capsule(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn decode_deployment(&self, bytes: &[u8]) -> ManifestResult<DeploymentManifest> {
        let normalized = self.preflight_decode(bytes)?;
        self.wire_codec().decode_deployment(&normalized)
    }

    fn encode_deployment(&self, manifest: &DeploymentManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_deployment(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn decode_binding(&self, bytes: &[u8]) -> ManifestResult<BindingManifest> {
        let normalized = self.preflight_decode(bytes)?;
        self.wire_codec().decode_binding(&normalized)
    }

    fn encode_binding(&self, manifest: &BindingManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_binding(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn decode_trigger(&self, bytes: &[u8]) -> ManifestResult<TriggerManifest> {
        let normalized = self.preflight_decode(bytes)?;
        self.wire_codec().decode_trigger(&normalized)
    }

    fn encode_trigger(&self, manifest: &TriggerManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_trigger(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn decode_policy(&self, bytes: &[u8]) -> ManifestResult<PolicyManifest> {
        let normalized = self.preflight_decode(bytes)?;
        self.wire_codec().decode_policy(&normalized)
    }

    fn encode_policy(&self, manifest: &PolicyManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_policy(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }
}

fn enforce_raw_limits(bytes: &[u8], limits: ManifestLimits) -> ManifestResult<()> {
    if bytes.len() > limits.max_document_bytes {
        return Err(vec![ManifestViolation::new(
            "$",
            "payload-too-large",
            format!(
                "manifest payload is {} bytes; configured maximum is {} bytes",
                bytes.len(),
                limits.max_document_bytes
            ),
        )]);
    }

    let mut depth = 0_usize;
    let mut in_string = false;
    let mut escaped = false;
    let mut string_start = 0_usize;

    for (index, byte) in bytes.iter().copied().enumerate() {
        if in_string {
            if escaped {
                escaped = false;
                continue;
            }
            match byte {
                b'\\' => escaped = true,
                b'"' => {
                    let raw_length = index.saturating_sub(string_start);
                    if raw_length > limits.max_string_bytes {
                        return Err(vec![ManifestViolation::new(
                            "$",
                            "string-too-large",
                            format!(
                                "a JSON string uses {raw_length} encoded bytes; configured maximum is {} bytes",
                                limits.max_string_bytes
                            ),
                        )]);
                    }
                    in_string = false;
                }
                _ => {}
            }
            continue;
        }

        match byte {
            b'"' => {
                in_string = true;
                string_start = index.saturating_add(1);
            }
            b'{' | b'[' => {
                depth = depth.saturating_add(1);
                if depth > limits.max_nesting_depth {
                    return Err(vec![ManifestViolation::new(
                        "$",
                        "nesting-limit-exceeded",
                        format!(
                            "manifest nesting depth exceeds the configured maximum of {}",
                            limits.max_nesting_depth
                        ),
                    )]);
                }
            }
            b'}' | b']' => depth = depth.saturating_sub(1),
            _ => {}
        }
    }

    Ok(())
}

fn enforce_collection_limit(bytes: &[u8], maximum: usize) -> ManifestResult<()> {
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let result = CollectionLimitSeed { maximum }
        .deserialize(&mut deserializer)
        .and_then(|()| deserializer.end());
    result.map_err(|error| {
        let message = error.to_string();
        let code = if message.contains(COLLECTION_LIMIT_MARKER) {
            "collection-limit-exceeded"
        } else {
            "malformed-json"
        };
        vec![ManifestViolation::new(
            "$",
            code,
            format!(
                "manifest JSON preflight failed at line {}, column {}: {message}",
                error.line(),
                error.column()
            ),
        )]
    })
}

#[derive(Clone, Copy)]
struct CollectionLimitSeed {
    maximum: usize,
}

impl<'de> DeserializeSeed<'de> for CollectionLimitSeed {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_any(CollectionLimitVisitor {
            maximum: self.maximum,
        })
    }
}

struct CollectionLimitVisitor {
    maximum: usize,
}

impl<'de> Visitor<'de> for CollectionLimitVisitor {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("bounded JSON")
    }

    fn visit_bool<E>(self, _value: bool) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_i64<E>(self, _value: i64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_i128<E>(self, _value: i128) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_u64<E>(self, _value: u64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_u128<E>(self, _value: u128) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_f64<E>(self, _value: f64) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_str<E>(self, _value: &str) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_borrowed_str<E>(self, _value: &'de str) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_string<E>(self, _value: String) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(())
    }

    fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        CollectionLimitSeed {
            maximum: self.maximum,
        }
        .deserialize(deserializer)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        if sequence
            .size_hint()
            .is_some_and(|length| length > self.maximum)
        {
            return Err(collection_limit_error(self.maximum));
        }

        let mut index = 0_usize;
        loop {
            let next = sequence.next_element_seed(BoundedValueSeed {
                maximum: self.maximum,
                index,
            })?;
            if next.is_none() {
                break;
            }
            index = index.saturating_add(1);
        }
        Ok(())
    }

    fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        if object
            .size_hint()
            .is_some_and(|length| length > self.maximum)
        {
            return Err(collection_limit_error(self.maximum));
        }

        let mut index = 0_usize;
        loop {
            let key = object.next_key_seed(BoundedKeySeed {
                maximum: self.maximum,
                index,
            })?;
            if key.is_none() {
                break;
            }
            object.next_value_seed(CollectionLimitSeed {
                maximum: self.maximum,
            })?;
            index = index.saturating_add(1);
        }
        Ok(())
    }
}

struct BoundedValueSeed {
    maximum: usize,
    index: usize,
}

impl<'de> DeserializeSeed<'de> for BoundedValueSeed {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        if self.index >= self.maximum {
            return Err(collection_limit_error(self.maximum));
        }
        CollectionLimitSeed {
            maximum: self.maximum,
        }
        .deserialize(deserializer)
    }
}

struct BoundedKeySeed {
    maximum: usize,
    index: usize,
}

impl<'de> DeserializeSeed<'de> for BoundedKeySeed {
    type Value = ();

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        if self.index >= self.maximum {
            return Err(collection_limit_error(self.maximum));
        }
        IgnoredAny::deserialize(deserializer).map(|_| ())
    }
}

fn collection_limit_error<E: de::Error>(maximum: usize) -> E {
    E::custom(format!(
        "{COLLECTION_LIMIT_MARKER}; configured maximum is {maximum} entries"
    ))
}

fn normalize_integral_number_lexemes(bytes: &[u8]) -> Vec<u8> {
    let mut output = Vec::with_capacity(bytes.len());
    let mut index = 0_usize;
    let mut in_string = false;
    let mut escaped = false;

    while index < bytes.len() {
        let byte = bytes[index];
        if in_string {
            output.push(byte);
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                in_string = false;
            }
            index += 1;
            continue;
        }

        if byte == b'"' {
            in_string = true;
            output.push(byte);
            index += 1;
            continue;
        }

        if byte == b'-' || byte.is_ascii_digit() {
            let start = index;
            index += 1;
            while index < bytes.len() && !is_number_delimiter(bytes[index]) {
                index += 1;
            }
            let token = &bytes[start..index];
            if let Some(integer) = representable_integer_lexeme(token) {
                output.extend_from_slice(&integer);
            } else {
                output.extend_from_slice(token);
            }
            continue;
        }

        output.push(byte);
        index += 1;
    }

    output
}

const fn is_number_delimiter(byte: u8) -> bool {
    matches!(byte, b' ' | b'\t' | b'\r' | b'\n' | b',' | b']' | b'}')
}
