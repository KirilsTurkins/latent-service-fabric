use std::collections::HashSet;
use std::fmt;

use serde::de::{self, DeserializeOwned, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde::Deserialize;
use serde_json::Value;

use crate::json_number::representable_integer_lexeme;
use crate::schema::validate_schema;
use crate::wire_codec::{
    JsonManifestCodec as WireJsonManifestCodec, ManifestLimits as WireManifestLimits,
};
use crate::{
    BindingManifest, CapsuleManifest, DeploymentManifest, ManifestCodec, ManifestDocument,
    ManifestKind, ManifestResult, ManifestViolation, PolicyManifest, TriggerManifest,
};

const DEFAULT_MAX_DOCUMENT_BYTES: usize = 1024 * 1024;
const DEFAULT_MAX_NESTING_DEPTH: usize = 64;
const DEFAULT_MAX_STRING_BYTES: usize = 256 * 1024;
const DEFAULT_MAX_COLLECTION_ENTRIES: usize = 4096;
const DEFAULT_MAX_VIOLATIONS: usize = 128;
const COLLECTION_LIMIT_MARKER: &str = "manifest collection entry limit exceeded";
const DUPLICATE_KEY_MARKER: &str = "duplicate object key";

/// Resource-consumption limits applied before and during JSON decoding.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ManifestLimits {
    pub max_document_bytes: usize,
    pub max_nesting_depth: usize,
    pub max_string_bytes: usize,
    /// Maximum number of entries in any one JSON array or object. A streaming
    /// preflight enforces the limit before a complete collection is allocated.
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

/// Bounded public JSON codec. Decoding retains arbitrary-precision JSON
/// numbers, applies the embedded schema, and only then constructs the typed
/// model. The inner wire codec remains the single serialization authority.
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
        let value = self.parse_exact(bytes)?;
        let kind = document_kind(&value)?;
        let document = self.decode_preparsed(kind, value)?;
        self.encode_document(&document)?;
        Ok(document)
    }

    /// Canonically encodes a type-erased manifest.
    pub fn encode_document(&self, manifest: &ManifestDocument) -> ManifestResult<Vec<u8>> {
        match manifest {
            ManifestDocument::Capsule(value) => self.encode_capsule(value),
            ManifestDocument::Deployment(value) => self.encode_deployment(value),
            ManifestDocument::Binding(value) => self.encode_binding(value),
            ManifestDocument::Trigger(value) => self.encode_trigger(value),
            ManifestDocument::Policy(value) => self.encode_policy(value),
        }
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
        enforce_collection_limit_and_unique_keys(bytes, self.limits.max_collection_entries)?;

        let normalized = normalize_number_lexemes(bytes);
        enforce_raw_limits(&normalized, self.limits)?;
        Ok(normalized)
    }

    fn preflight_encoded(&self, bytes: &[u8]) -> ManifestResult<()> {
        enforce_raw_limits(bytes, self.limits)?;
        enforce_collection_limit_and_unique_keys(bytes, self.limits.max_collection_entries)
    }

    fn parse_exact(&self, bytes: &[u8]) -> ManifestResult<Value> {
        let normalized = self.preflight_decode(bytes)?;
        let mut deserializer = serde_json::Deserializer::from_slice(&normalized);
        Value::deserialize(&mut deserializer)
            .and_then(|value| deserializer.end().map(|()| value))
            .map_err(|error| {
                vec![ManifestViolation::new(
                    "$",
                    "malformed-json",
                    format!(
                        "manifest JSON could not be decoded at line {}, column {}: {error}",
                        error.line(),
                        error.column()
                    ),
                )]
            })
    }

    fn decode_kind<T>(&self, bytes: &[u8], kind: ManifestKind) -> ManifestResult<T>
    where
        T: DeserializeOwned + Normalize,
    {
        let value = self.parse_exact(bytes)?;
        self.validate_and_decode(value, kind)
    }

    fn decode_preparsed(
        &self,
        kind: ManifestKind,
        value: Value,
    ) -> ManifestResult<ManifestDocument> {
        match kind {
            ManifestKind::Capsule => self
                .validate_and_decode(value, kind)
                .map(ManifestDocument::Capsule),
            ManifestKind::Deployment => self
                .validate_and_decode(value, kind)
                .map(ManifestDocument::Deployment),
            ManifestKind::Binding => self
                .validate_and_decode(value, kind)
                .map(ManifestDocument::Binding),
            ManifestKind::Trigger => self
                .validate_and_decode(value, kind)
                .map(ManifestDocument::Trigger),
            ManifestKind::Policy => self
                .validate_and_decode(value, kind)
                .map(ManifestDocument::Policy),
        }
    }

    fn validate_and_decode<T>(&self, value: Value, kind: ManifestKind) -> ManifestResult<T>
    where
        T: DeserializeOwned + Normalize,
    {
        let violations = validate_schema(kind, &value, self.limits.max_violations.max(1));
        if !violations.is_empty() {
            return Err(violations);
        }

        let mut decoded: T = serde_json::from_value(value).map_err(|error| {
            vec![ManifestViolation::new(
                "$",
                "model-decode-failed",
                format!("schema-valid JSON could not be represented by the Rust model: {error}"),
            )]
        })?;
        decoded.normalize();
        Ok(decoded)
    }
}

impl ManifestCodec for JsonManifestCodec {
    fn decode_capsule(&self, bytes: &[u8]) -> ManifestResult<CapsuleManifest> {
        let manifest = self.decode_kind(bytes, ManifestKind::Capsule)?;
        self.encode_capsule(&manifest)?;
        Ok(manifest)
    }

    fn encode_capsule(&self, manifest: &CapsuleManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_capsule(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn decode_deployment(&self, bytes: &[u8]) -> ManifestResult<DeploymentManifest> {
        let manifest = self.decode_kind(bytes, ManifestKind::Deployment)?;
        self.encode_deployment(&manifest)?;
        Ok(manifest)
    }

    fn encode_deployment(&self, manifest: &DeploymentManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_deployment(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn decode_binding(&self, bytes: &[u8]) -> ManifestResult<BindingManifest> {
        let manifest = self.decode_kind(bytes, ManifestKind::Binding)?;
        self.encode_binding(&manifest)?;
        Ok(manifest)
    }

    fn encode_binding(&self, manifest: &BindingManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_binding(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn decode_trigger(&self, bytes: &[u8]) -> ManifestResult<TriggerManifest> {
        let manifest = self.decode_kind(bytes, ManifestKind::Trigger)?;
        self.encode_trigger(&manifest)?;
        Ok(manifest)
    }

    fn encode_trigger(&self, manifest: &TriggerManifest) -> ManifestResult<Vec<u8>> {
        let mut normalized = manifest.clone();
        normalized.normalize();
        let bytes = self.wire_codec().encode_trigger(&normalized)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }

    fn decode_policy(&self, bytes: &[u8]) -> ManifestResult<PolicyManifest> {
        let manifest = self.decode_kind(bytes, ManifestKind::Policy)?;
        self.encode_policy(&manifest)?;
        Ok(manifest)
    }

    fn encode_policy(&self, manifest: &PolicyManifest) -> ManifestResult<Vec<u8>> {
        let bytes = self.wire_codec().encode_policy(manifest)?;
        self.preflight_encoded(&bytes)?;
        Ok(bytes)
    }
}

fn document_kind(value: &Value) -> ManifestResult<ManifestKind> {
    let object = value.as_object().ok_or_else(|| {
        vec![ManifestViolation::new(
            "$",
            "invalid-type",
            "a manifest document must be a JSON object",
        )]
    })?;
    let kind = object.get("kind").ok_or_else(|| {
        vec![ManifestViolation::new(
            "$.kind",
            "missing-field",
            "required field `kind` is missing",
        )]
    })?;
    let kind = kind.as_str().ok_or_else(|| {
        vec![ManifestViolation::new(
            "$.kind",
            "invalid-type",
            "field `kind` must be a string",
        )]
    })?;
    match kind {
        "Capsule" => Ok(ManifestKind::Capsule),
        "Deployment" => Ok(ManifestKind::Deployment),
        "Binding" => Ok(ManifestKind::Binding),
        "Policy" => Ok(ManifestKind::Policy),
        "HttpTrigger"
        | "EventTrigger"
        | "TimerTrigger"
        | "QueueTrigger"
        | "BlobTrigger"
        | "DirectInvocationTrigger" => Ok(ManifestKind::Trigger),
        _ => Err(vec![ManifestViolation::new(
            "$.kind",
            "unexpected-kind",
            format!("unsupported manifest kind `{kind}`"),
        )]),
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

fn enforce_collection_limit_and_unique_keys(bytes: &[u8], maximum: usize) -> ManifestResult<()> {
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let result = CollectionLimitSeed { maximum }
        .deserialize(&mut deserializer)
        .and_then(|()| deserializer.end());
    result.map_err(|error| {
        let message = error.to_string();
        let code = if message.contains(COLLECTION_LIMIT_MARKER) {
            "collection-limit-exceeded"
        } else if message.contains(DUPLICATE_KEY_MARKER) {
            "duplicate-key"
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
        let mut keys = HashSet::new();
        loop {
            let key = object.next_key_seed(BoundedKeySeed {
                maximum: self.maximum,
                index,
            })?;
            let Some(key) = key else {
                break;
            };
            if !keys.insert(key.clone()) {
                return Err(duplicate_key_error(&key));
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
    type Value = String;

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        if self.index >= self.maximum {
            return Err(collection_limit_error(self.maximum));
        }
        String::deserialize(deserializer)
    }
}

fn collection_limit_error<E: de::Error>(maximum: usize) -> E {
    E::custom(format!(
        "{COLLECTION_LIMIT_MARKER}; configured maximum is {maximum} entries"
    ))
}

fn duplicate_key_error<E: de::Error>(key: &str) -> E {
    E::custom(format!("{DUPLICATE_KEY_MARKER} `{key}`"))
}

fn normalize_number_lexemes(bytes: &[u8]) -> Vec<u8> {
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
            if let Some(number) = representable_integer_lexeme(token) {
                output.extend_from_slice(&number);
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

trait Normalize {
    fn normalize(&mut self);
}

impl Normalize for CapsuleManifest {
    fn normalize(&mut self) {
        self.component_digest.0.make_ascii_lowercase();
        self.exports
            .sort_by(|left, right| left.contract.cmp(&right.contract));
        self.imports.sort_by(|left, right| {
            (&left.contract, left.optional).cmp(&(&right.contract, right.optional))
        });
    }
}

impl Normalize for DeploymentManifest {
    fn normalize(&mut self) {
        self.release.0.make_ascii_lowercase();
        for grant in &mut self.grants {
            grant.operations.sort();
        }
        self.grants.sort_by(|left, right| {
            (&left.capability, &left.policy, &left.operations).cmp(&(
                &right.capability,
                &right.policy,
                &right.operations,
            ))
        });
        self.placement.architectures.sort();
        self.placement.regions.sort();
        self.placement.zones.sort();
        self.placement.required_features.sort();
    }
}

impl Normalize for BindingManifest {
    fn normalize(&mut self) {}
}

impl Normalize for TriggerManifest {
    fn normalize(&mut self) {
        for value in self.configuration.values_mut() {
            canonicalize_json_value(value);
        }
    }
}

impl Normalize for PolicyManifest {
    fn normalize(&mut self) {}
}

fn canonicalize_json_value(value: &mut Value) {
    match value {
        Value::Array(values) => {
            for value in values {
                canonicalize_json_value(value);
            }
        }
        Value::Object(object) => {
            let mut entries: Vec<_> = std::mem::take(object).into_iter().collect();
            entries.sort_by(|left, right| left.0.cmp(&right.0));
            for (key, mut value) in entries {
                canonicalize_json_value(&mut value);
                object.insert(key, value);
            }
        }
        Value::Number(number) => {
            let canonical = representable_integer_lexeme(number.as_str().as_bytes())
                .expect("serde_json::Number always stores valid JSON-number syntax");
            *number = serde_json::from_slice(&canonical)
                .expect("value-canonical JSON-number syntax remains valid");
        }
        Value::Null | Value::Bool(_) | Value::String(_) => {}
    }
}
