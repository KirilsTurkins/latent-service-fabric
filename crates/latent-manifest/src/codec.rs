use std::collections::BTreeMap;
use std::fmt;

use latent_core::{
    BindingId, CapabilityId, ContractId, DeploymentId, Metadata, PolicyId, ReleaseDigest,
    ResourceBudget, ServiceId, TenantId, TriggerId,
};
use serde::de::{self, DeserializeOwned, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::{Map, Number, Value};

use crate::schema::{schema_text, validate_schema};
use crate::{
    AvailabilityPolicy, BindingEndpoint, BindingManifest, BindingMode, CapabilityGrantSpec,
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    JsonObject, ManifestCodec, ManifestResult, ManifestViolation, ObjectMetadata, PlacementPolicy,
    PolicyManifest, StateModel, ThreadingModel, TriggerKind, TriggerManifest, TriggerTarget,
};

const DEFAULT_MAX_DOCUMENT_BYTES: usize = 1024 * 1024;
const DEFAULT_MAX_NESTING_DEPTH: usize = 64;
const DEFAULT_MAX_STRING_BYTES: usize = 256 * 1024;
const DEFAULT_MAX_VIOLATIONS: usize = 128;
const DUPLICATE_KEY_MARKER: &str = "duplicate object key";

/// Manifest family backed by one canonical schema.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ManifestKind {
    Capsule,
    Deployment,
    Binding,
    Trigger,
    Policy,
}

impl ManifestKind {
    /// Returns the checked-in canonical schema text embedded in this crate.
    #[must_use]
    pub fn schema(self) -> &'static str {
        schema_text(self)
    }

    fn from_wire_kind(kind: &str) -> Option<Self> {
        match kind {
            "Capsule" => Some(Self::Capsule),
            "Deployment" => Some(Self::Deployment),
            "Binding" => Some(Self::Binding),
            "Policy" => Some(Self::Policy),
            "HttpTrigger"
            | "EventTrigger"
            | "TimerTrigger"
            | "QueueTrigger"
            | "BlobTrigger"
            | "DirectInvocationTrigger" => Some(Self::Trigger),
            _ => None,
        }
    }
}

/// Type-erased decoded manifest used by generic admission and tooling paths.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ManifestDocument {
    Capsule(CapsuleManifest),
    Deployment(DeploymentManifest),
    Binding(BindingManifest),
    Trigger(TriggerManifest),
    Policy(PolicyManifest),
}

impl ManifestDocument {
    #[must_use]
    pub const fn kind(&self) -> ManifestKind {
        match self {
            Self::Capsule(_) => ManifestKind::Capsule,
            Self::Deployment(_) => ManifestKind::Deployment,
            Self::Binding(_) => ManifestKind::Binding,
            Self::Trigger(_) => ManifestKind::Trigger,
            Self::Policy(_) => ManifestKind::Policy,
        }
    }
}

/// Resource-consumption limits applied before and during JSON decoding.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ManifestLimits {
    pub max_document_bytes: usize,
    pub max_nesting_depth: usize,
    pub max_string_bytes: usize,
    pub max_violations: usize,
}

impl Default for ManifestLimits {
    fn default() -> Self {
        Self {
            max_document_bytes: DEFAULT_MAX_DOCUMENT_BYTES,
            max_nesting_depth: DEFAULT_MAX_NESTING_DEPTH,
            max_string_bytes: DEFAULT_MAX_STRING_BYTES,
            max_violations: DEFAULT_MAX_VIOLATIONS,
        }
    }
}

/// Bounded, schema-backed JSON implementation of [`ManifestCodec`].
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
        let value = self.parse_limited(bytes)?;
        let kind = document_kind(&value)?;
        self.decode_preparsed(kind, value)
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

    fn decode_kind<T>(&self, bytes: &[u8], kind: ManifestKind) -> ManifestResult<T>
    where
        T: DeserializeOwned + Normalize,
    {
        let value = self.parse_limited(bytes)?;
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
        let maximum = self.limits.max_violations.max(1);
        let mut violations = validate_schema(kind, &value, maximum);
        validate_model_integer_ranges(kind, &value, &mut violations, maximum);
        violations.sort();
        violations.dedup();
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

    fn parse_limited(&self, bytes: &[u8]) -> ManifestResult<Value> {
        enforce_raw_limits(bytes, self.limits)?;

        let mut deserializer = serde_json::Deserializer::from_slice(bytes);
        let parsed = UniqueValue::deserialize(&mut deserializer)
            .and_then(|value| deserializer.end().map(|()| value));
        parsed.map(|value| value.0).map_err(|error| {
            let message = error.to_string();
            let code = if message.contains(DUPLICATE_KEY_MARKER) {
                "duplicate-key"
            } else {
                "malformed-json"
            };
            vec![ManifestViolation::new(
                "$",
                code,
                format!(
                    "manifest JSON could not be decoded at line {}, column {}: {message}",
                    error.line(),
                    error.column()
                ),
            )]
        })
    }

    fn encode_normalized<T>(&self, value: &T, kind: ManifestKind) -> ManifestResult<Vec<u8>>
    where
        T: Serialize,
    {
        let mut encoded = serde_json::to_value(value).map_err(|error| {
            vec![ManifestViolation::new(
                "$",
                "model-encode-failed",
                format!("the Rust manifest could not be represented as JSON: {error}"),
            )]
        })?;
        canonicalize_json_value(&mut encoded);

        let violations = validate_schema(kind, &encoded, self.limits.max_violations.max(1));
        if !violations.is_empty() {
            return Err(violations);
        }

        let bytes = serde_json::to_vec(&encoded).map_err(|error| {
            vec![ManifestViolation::new(
                "$",
                "model-encode-failed",
                format!("the canonical JSON value could not be encoded: {error}"),
            )]
        })?;
        enforce_raw_limits(&bytes, self.limits)?;
        Ok(bytes)
    }
}

impl ManifestCodec for JsonManifestCodec {
    fn decode_capsule(&self, bytes: &[u8]) -> ManifestResult<CapsuleManifest> {
        self.decode_kind(bytes, ManifestKind::Capsule)
    }

    fn encode_capsule(&self, manifest: &CapsuleManifest) -> ManifestResult<Vec<u8>> {
        let mut normalized = manifest.clone();
        normalized.normalize();
        self.encode_normalized(&normalized, ManifestKind::Capsule)
    }

    fn decode_deployment(&self, bytes: &[u8]) -> ManifestResult<DeploymentManifest> {
        self.decode_kind(bytes, ManifestKind::Deployment)
    }

    fn encode_deployment(&self, manifest: &DeploymentManifest) -> ManifestResult<Vec<u8>> {
        ensure_wire_identity(&manifest.id.0, &manifest.metadata.name)?;
        let mut normalized = manifest.clone();
        normalized.normalize();
        self.encode_normalized(&normalized, ManifestKind::Deployment)
    }

    fn decode_binding(&self, bytes: &[u8]) -> ManifestResult<BindingManifest> {
        self.decode_kind(bytes, ManifestKind::Binding)
    }

    fn encode_binding(&self, manifest: &BindingManifest) -> ManifestResult<Vec<u8>> {
        ensure_wire_identity(&manifest.id.0, &manifest.metadata.name)?;
        let mut normalized = manifest.clone();
        normalized.normalize();
        self.encode_normalized(&normalized, ManifestKind::Binding)
    }

    fn decode_trigger(&self, bytes: &[u8]) -> ManifestResult<TriggerManifest> {
        self.decode_kind(bytes, ManifestKind::Trigger)
    }

    fn encode_trigger(&self, manifest: &TriggerManifest) -> ManifestResult<Vec<u8>> {
        ensure_wire_identity(&manifest.id.0, &manifest.metadata.name)?;
        let mut normalized = manifest.clone();
        normalized.normalize();
        self.encode_normalized(&normalized, ManifestKind::Trigger)
    }

    fn decode_policy(&self, bytes: &[u8]) -> ManifestResult<PolicyManifest> {
        self.decode_kind(bytes, ManifestKind::Policy)
    }

    fn encode_policy(&self, manifest: &PolicyManifest) -> ManifestResult<Vec<u8>> {
        ensure_wire_identity(&manifest.id.0, &manifest.metadata.name)?;
        let mut normalized = manifest.clone();
        normalized.normalize();
        self.encode_normalized(&normalized, ManifestKind::Policy)
    }
}

fn ensure_wire_identity(id: &str, metadata_name: &str) -> ManifestResult<()> {
    if id == metadata_name {
        Ok(())
    } else {
        Err(vec![ManifestViolation::new(
            "$.metadata.name",
            "identity-mismatch",
            "the domain ID must equal metadata.name because the JSON resource has one identity field",
        )])
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
    ManifestKind::from_wire_kind(kind).ok_or_else(|| {
        vec![ManifestViolation::new(
            "$.kind",
            "unexpected-kind",
            format!("unsupported manifest kind `{kind}`"),
        )]
    })
}

fn validate_model_integer_ranges(
    kind: ManifestKind,
    value: &Value,
    violations: &mut Vec<ManifestViolation>,
    maximum: usize,
) {
    let fields: &[(&str, &str, u64)] = match kind {
        ManifestKind::Capsule => &[
            (
                "/execution/hostCallDepthMaximum",
                "$.execution.hostCallDepthMaximum",
                u64::from(u32::MAX),
            ),
            (
                "/execution/componentCallDepthMaximum",
                "$.execution.componentCallDepthMaximum",
                u64::from(u32::MAX),
            ),
            (
                "/execution/limits/childCalls",
                "$.execution.limits.childCalls",
                u64::from(u32::MAX),
            ),
            (
                "/execution/limits/outboundRequests",
                "$.execution.limits.outboundRequests",
                u64::from(u32::MAX),
            ),
            (
                "/execution/limits/effectCount",
                "$.execution.limits.effectCount",
                u64::from(u32::MAX),
            ),
        ],
        ManifestKind::Deployment => &[
            (
                "/spec/route/weight",
                "$.spec.route.weight",
                u64::from(u16::MAX),
            ),
            (
                "/spec/resources/childCalls",
                "$.spec.resources.childCalls",
                u64::from(u32::MAX),
            ),
            (
                "/spec/resources/outboundRequests",
                "$.spec.resources.outboundRequests",
                u64::from(u32::MAX),
            ),
            (
                "/spec/resources/effectCount",
                "$.spec.resources.effectCount",
                u64::from(u32::MAX),
            ),
            (
                "/spec/availability/minimumCachedCopies",
                "$.spec.availability.minimumCachedCopies",
                u64::from(u32::MAX),
            ),
            (
                "/spec/availability/minimumZones",
                "$.spec.availability.minimumZones",
                u64::from(u32::MAX),
            ),
        ],
        ManifestKind::Binding | ManifestKind::Trigger | ManifestKind::Policy => &[],
    };

    for (pointer, path, upper_bound) in fields {
        let Some(number) = value.pointer(pointer).and_then(Value::as_number) else {
            continue;
        };
        if number.as_u64().is_none_or(|number| number > *upper_bound) && violations.len() < maximum
        {
            violations.push(ManifestViolation::new(
                *path,
                "out-of-range",
                format!("integer must be between 0 and {upper_bound}"),
            ));
        }
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

#[derive(Debug)]
struct UniqueValue(Value);

impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(UniqueValueVisitor)
    }
}

struct UniqueValueVisitor;

impl<'de> Visitor<'de> for UniqueValueVisitor {
    type Value = UniqueValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON value without duplicate object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Number(Number::from(value))))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Number(Number::from(value))))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        Number::from_f64(value)
            .map(Value::Number)
            .map(UniqueValue)
            .ok_or_else(|| E::custom("non-finite JSON number"))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        self.visit_string(value.to_owned())
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::String(value)))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        UniqueValue::deserialize(deserializer)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(UniqueValue(value)) = sequence.next_element()? {
            values.push(value);
        }
        Ok(UniqueValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut values = Map::new();
        while let Some(key) = object.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(de::Error::custom(format!("{DUPLICATE_KEY_MARKER} `{key}`")));
            }
            let UniqueValue(value) = object.next_value()?;
            values.insert(key, value);
        }
        Ok(UniqueValue(Value::Object(values)))
    }
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
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
enum FixedKind {
    Capsule,
    Deployment,
    Binding,
    Policy,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ObjectMetadataWire {
    name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    tenant: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    namespace: Option<String>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    labels: Metadata,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    annotations: Metadata,
}

impl From<&ObjectMetadata> for ObjectMetadataWire {
    fn from(value: &ObjectMetadata) -> Self {
        Self {
            name: value.name.clone(),
            tenant: value.tenant.as_ref().map(|tenant| tenant.0.clone()),
            namespace: value.namespace.clone(),
            labels: value.labels.clone(),
            annotations: value.annotations.clone(),
        }
    }
}

impl ObjectMetadataWire {
    fn into_domain(self) -> ObjectMetadata {
        ObjectMetadata {
            name: self.name,
            tenant: self.tenant.map(TenantId),
            namespace: self.namespace,
            labels: self.labels,
            annotations: self.annotations,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResourceBudgetWire {
    cpu_fuel: u64,
    memory_bytes: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    wall_time_limit_millis: Option<u64>,
    child_calls: u32,
    outbound_requests: u32,
    state_read_bytes: u64,
    state_write_bytes: u64,
    blob_read_bytes: u64,
    blob_write_bytes: u64,
    log_bytes: u64,
    effect_count: u32,
}

impl From<&ResourceBudget> for ResourceBudgetWire {
    fn from(value: &ResourceBudget) -> Self {
        Self {
            cpu_fuel: value.cpu_fuel,
            memory_bytes: value.memory_bytes,
            wall_time_limit_millis: value.wall_time_limit_millis,
            child_calls: value.child_calls,
            outbound_requests: value.outbound_requests,
            state_read_bytes: value.state_read_bytes,
            state_write_bytes: value.state_write_bytes,
            blob_read_bytes: value.blob_read_bytes,
            blob_write_bytes: value.blob_write_bytes,
            log_bytes: value.log_bytes,
            effect_count: value.effect_count,
        }
    }
}

impl ResourceBudgetWire {
    fn into_domain(self) -> ResourceBudget {
        ResourceBudget {
            cpu_fuel: self.cpu_fuel,
            memory_bytes: self.memory_bytes,
            wall_time_limit_millis: self.wall_time_limit_millis,
            child_calls: self.child_calls,
            outbound_requests: self.outbound_requests,
            state_read_bytes: self.state_read_bytes,
            state_write_bytes: self.state_write_bytes,
            blob_read_bytes: self.blob_read_bytes,
            blob_write_bytes: self.blob_write_bytes,
            log_bytes: self.log_bytes,
            effect_count: self.effect_count,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CapsuleComponentWire {
    digest: String,
    version: String,
    world: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ContractImportWire {
    contract: String,
    #[serde(default)]
    optional: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExecutionRequirementsWire {
    backend: ExecutionBackendKind,
    threading: ThreadingModel,
    state_model: StateModel,
    limits: ResourceBudgetWire,
    #[serde(default = "default_call_depth")]
    host_call_depth_maximum: u32,
    #[serde(default = "default_call_depth")]
    component_call_depth_maximum: u32,
    #[serde(default)]
    snapshot_eligible: bool,
    #[serde(default)]
    fusion_eligible: bool,
}

const fn default_call_depth() -> u32 {
    1
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CapsuleCompatibilityWire {
    minimum_fabric_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CapsuleDocumentWire {
    api_version: String,
    kind: FixedKind,
    metadata: ObjectMetadataWire,
    component: CapsuleComponentWire,
    exports: Vec<String>,
    imports: Vec<ContractImportWire>,
    execution: ExecutionRequirementsWire,
    compatibility: CapsuleCompatibilityWire,
}

impl Serialize for CapsuleManifest {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        CapsuleDocumentWire::from(self).serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for CapsuleManifest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let document = CapsuleDocumentWire::deserialize(deserializer)?;
        if document.kind != FixedKind::Capsule {
            return Err(de::Error::custom("manifest kind must be Capsule"));
        }
        Ok(document.into())
    }
}

impl From<&CapsuleManifest> for CapsuleDocumentWire {
    fn from(value: &CapsuleManifest) -> Self {
        Self {
            api_version: value.api_version.clone(),
            kind: FixedKind::Capsule,
            metadata: ObjectMetadataWire::from(&value.metadata),
            component: CapsuleComponentWire {
                digest: value.component_digest.0.clone(),
                version: value.semantic_version.clone(),
                world: value.world.0.clone(),
            },
            exports: value
                .exports
                .iter()
                .map(|export| export.contract.0.clone())
                .collect(),
            imports: value
                .imports
                .iter()
                .map(|import| ContractImportWire {
                    contract: import.contract.0.clone(),
                    optional: import.optional,
                })
                .collect(),
            execution: ExecutionRequirementsWire {
                backend: value.execution.backend,
                threading: value.execution.threading,
                state_model: value.execution.state_model,
                limits: ResourceBudgetWire::from(&value.execution.resource_budget_ceiling),
                host_call_depth_maximum: value.execution.host_call_depth_maximum,
                component_call_depth_maximum: value.execution.component_call_depth_maximum,
                snapshot_eligible: value.execution.snapshot_eligible,
                fusion_eligible: value.execution.fusion_eligible,
            },
            compatibility: CapsuleCompatibilityWire {
                minimum_fabric_version: value.minimum_fabric_version.clone(),
            },
        }
    }
}

impl From<CapsuleDocumentWire> for CapsuleManifest {
    fn from(value: CapsuleDocumentWire) -> Self {
        Self {
            api_version: value.api_version,
            metadata: value.metadata.into_domain(),
            semantic_version: value.component.version,
            component_digest: ReleaseDigest(value.component.digest),
            world: ContractId(value.component.world),
            exports: value
                .exports
                .into_iter()
                .map(|contract| ContractExport {
                    contract: ContractId(contract),
                })
                .collect(),
            imports: value
                .imports
                .into_iter()
                .map(|import| ContractImport {
                    contract: ContractId(import.contract),
                    optional: import.optional,
                })
                .collect(),
            execution: ExecutionRequirements {
                backend: value.execution.backend,
                threading: value.execution.threading,
                state_model: value.execution.state_model,
                resource_budget_ceiling: value.execution.limits.into_domain(),
                host_call_depth_maximum: value.execution.host_call_depth_maximum,
                component_call_depth_maximum: value.execution.component_call_depth_maximum,
                snapshot_eligible: value.execution.snapshot_eligible,
                fusion_eligible: value.execution.fusion_eligible,
            },
            minimum_fabric_version: value.compatibility.minimum_fabric_version,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RouteWeightWire {
    weight: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CapabilityGrantWire {
    capability: String,
    policy: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    operations: Vec<String>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    constraints: Metadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AvailabilityPolicyWire {
    minimum_cached_copies: u32,
    minimum_zones: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PlacementPolicyWire {
    trust_class: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    architectures: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    regions: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    zones: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    required_features: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DeploymentSpecWire {
    service: String,
    release: String,
    route: RouteWeightWire,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    grants: Vec<CapabilityGrantWire>,
    resources: ResourceBudgetWire,
    availability: AvailabilityPolicyWire,
    placement: PlacementPolicyWire,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DeploymentDocumentWire {
    api_version: String,
    kind: FixedKind,
    metadata: ObjectMetadataWire,
    spec: DeploymentSpecWire,
}

impl Serialize for DeploymentManifest {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if self.id.0 != self.metadata.name {
            return Err(serde::ser::Error::custom(
                "deployment ID must equal metadata.name",
            ));
        }
        DeploymentDocumentWire::from(self).serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for DeploymentManifest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let document = DeploymentDocumentWire::deserialize(deserializer)?;
        if document.kind != FixedKind::Deployment {
            return Err(de::Error::custom("manifest kind must be Deployment"));
        }
        Ok(document.into())
    }
}

impl From<&DeploymentManifest> for DeploymentDocumentWire {
    fn from(value: &DeploymentManifest) -> Self {
        Self {
            api_version: value.api_version.clone(),
            kind: FixedKind::Deployment,
            metadata: ObjectMetadataWire::from(&value.metadata),
            spec: DeploymentSpecWire {
                service: value.service.0.clone(),
                release: value.release.0.clone(),
                route: RouteWeightWire {
                    weight: value.route_weight,
                },
                grants: value
                    .grants
                    .iter()
                    .map(|grant| CapabilityGrantWire {
                        capability: grant.capability.0.clone(),
                        policy: grant.policy.0.clone(),
                        operations: grant.operations.clone(),
                        constraints: grant.constraints.clone(),
                    })
                    .collect(),
                resources: ResourceBudgetWire::from(&value.resources),
                availability: AvailabilityPolicyWire {
                    minimum_cached_copies: value.availability.minimum_cached_copies,
                    minimum_zones: value.availability.minimum_zones,
                },
                placement: PlacementPolicyWire {
                    trust_class: value.placement.trust_class.clone(),
                    architectures: value.placement.architectures.clone(),
                    regions: value.placement.regions.clone(),
                    zones: value.placement.zones.clone(),
                    required_features: value.placement.required_features.clone(),
                },
            },
        }
    }
}

impl From<DeploymentDocumentWire> for DeploymentManifest {
    fn from(value: DeploymentDocumentWire) -> Self {
        let id = DeploymentId(value.metadata.name.clone());
        Self {
            api_version: value.api_version,
            id,
            metadata: value.metadata.into_domain(),
            service: ServiceId(value.spec.service),
            release: ReleaseDigest(value.spec.release),
            route_weight: value.spec.route.weight,
            grants: value
                .spec
                .grants
                .into_iter()
                .map(|grant| CapabilityGrantSpec {
                    capability: CapabilityId(grant.capability),
                    policy: PolicyId(grant.policy),
                    operations: grant.operations,
                    constraints: grant.constraints,
                })
                .collect(),
            resources: value.spec.resources.into_domain(),
            availability: AvailabilityPolicy {
                minimum_cached_copies: value.spec.availability.minimum_cached_copies,
                minimum_zones: value.spec.availability.minimum_zones,
            },
            placement: PlacementPolicy {
                trust_class: value.spec.placement.trust_class,
                architectures: value.spec.placement.architectures,
                regions: value.spec.placement.regions,
                zones: value.spec.placement.zones,
                required_features: value.spec.placement.required_features,
            },
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BindingEndpointWire {
    service: String,
    contract: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    route: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BindingSpecWire {
    consumer: BindingEndpointWire,
    provider: BindingEndpointWire,
    mode: BindingMode,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BindingDocumentWire {
    api_version: String,
    kind: FixedKind,
    metadata: ObjectMetadataWire,
    spec: BindingSpecWire,
}

impl Serialize for BindingManifest {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if self.id.0 != self.metadata.name {
            return Err(serde::ser::Error::custom(
                "binding ID must equal metadata.name",
            ));
        }
        BindingDocumentWire::from(self).serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for BindingManifest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let document = BindingDocumentWire::deserialize(deserializer)?;
        if document.kind != FixedKind::Binding {
            return Err(de::Error::custom("manifest kind must be Binding"));
        }
        Ok(document.into())
    }
}

impl From<&BindingManifest> for BindingDocumentWire {
    fn from(value: &BindingManifest) -> Self {
        Self {
            api_version: value.api_version.clone(),
            kind: FixedKind::Binding,
            metadata: ObjectMetadataWire::from(&value.metadata),
            spec: BindingSpecWire {
                consumer: BindingEndpointWire {
                    service: value.consumer.service.0.clone(),
                    contract: value.consumer.contract.0.clone(),
                    route: value.consumer.route.clone(),
                },
                provider: BindingEndpointWire {
                    service: value.provider.service.0.clone(),
                    contract: value.provider.contract.0.clone(),
                    route: value.provider.route.clone(),
                },
                mode: value.mode,
            },
        }
    }
}

impl From<BindingDocumentWire> for BindingManifest {
    fn from(value: BindingDocumentWire) -> Self {
        let id = BindingId(value.metadata.name.clone());
        Self {
            api_version: value.api_version,
            id,
            metadata: value.metadata.into_domain(),
            consumer: BindingEndpoint {
                service: ServiceId(value.spec.consumer.service),
                contract: ContractId(value.spec.consumer.contract),
                route: value.spec.consumer.route,
            },
            provider: BindingEndpoint {
                service: ServiceId(value.spec.provider.service),
                contract: ContractId(value.spec.provider.contract),
                route: value.spec.provider.route,
            },
            mode: value.spec.mode,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TriggerTargetWire {
    service: String,
    contract: String,
    function: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    route: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TriggerSpecWire {
    target: TriggerTargetWire,
    configuration: JsonObject,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TriggerDocumentWire {
    api_version: String,
    kind: TriggerKind,
    metadata: ObjectMetadataWire,
    spec: TriggerSpecWire,
}

impl Serialize for TriggerManifest {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if self.id.0 != self.metadata.name {
            return Err(serde::ser::Error::custom(
                "trigger ID must equal metadata.name",
            ));
        }
        TriggerDocumentWire::from(self).serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for TriggerManifest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        TriggerDocumentWire::deserialize(deserializer).map(Into::into)
    }
}

impl From<&TriggerManifest> for TriggerDocumentWire {
    fn from(value: &TriggerManifest) -> Self {
        Self {
            api_version: value.api_version.clone(),
            kind: value.kind,
            metadata: ObjectMetadataWire::from(&value.metadata),
            spec: TriggerSpecWire {
                target: TriggerTargetWire {
                    service: value.target.service.0.clone(),
                    contract: value.target.contract.0.clone(),
                    function: value.target.function.clone(),
                    route: value.target.route.clone(),
                },
                configuration: value.configuration.clone(),
            },
        }
    }
}

impl From<TriggerDocumentWire> for TriggerManifest {
    fn from(value: TriggerDocumentWire) -> Self {
        let id = TriggerId(value.metadata.name.clone());
        Self {
            api_version: value.api_version,
            id,
            metadata: value.metadata.into_domain(),
            kind: value.kind,
            target: TriggerTarget {
                service: ServiceId(value.spec.target.service),
                contract: ContractId(value.spec.target.contract),
                function: value.spec.target.function,
                route: value.spec.target.route,
            },
            configuration: value.spec.configuration,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PolicySpecWire {
    language: String,
    document: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PolicyDocumentWire {
    api_version: String,
    kind: FixedKind,
    metadata: ObjectMetadataWire,
    spec: PolicySpecWire,
}

impl Serialize for PolicyManifest {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if self.id.0 != self.metadata.name {
            return Err(serde::ser::Error::custom(
                "policy ID must equal metadata.name",
            ));
        }
        PolicyDocumentWire::from(self).serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for PolicyManifest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let document = PolicyDocumentWire::deserialize(deserializer)?;
        if document.kind != FixedKind::Policy {
            return Err(de::Error::custom("manifest kind must be Policy"));
        }
        Ok(document.into())
    }
}

impl From<&PolicyManifest> for PolicyDocumentWire {
    fn from(value: &PolicyManifest) -> Self {
        Self {
            api_version: value.api_version.clone(),
            kind: FixedKind::Policy,
            metadata: ObjectMetadataWire::from(&value.metadata),
            spec: PolicySpecWire {
                language: value.language.clone(),
                document: value.document.clone(),
            },
        }
    }
}

impl From<PolicyDocumentWire> for PolicyManifest {
    fn from(value: PolicyDocumentWire) -> Self {
        let id = PolicyId(value.metadata.name.clone());
        Self {
            api_version: value.api_version,
            id,
            metadata: value.metadata.into_domain(),
            language: value.spec.language,
            document: value.spec.document,
        }
    }
}
