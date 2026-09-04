use std::cmp::Ordering;
use std::collections::{BTreeSet, HashSet};
use std::sync::OnceLock;

use serde_json::{Number, Value};

use crate::json_number::{canonical_number_key, compare_numbers, is_mathematical_integer};
use crate::{ManifestKind, ManifestViolation};

const CAPSULE_SCHEMA_TEXT: &str = include_str!("../../../schemas/capsule-manifest.schema.json");
const DEPLOYMENT_SCHEMA_TEXT: &str = include_str!("../../../schemas/deployment.schema.json");
const BINDING_SCHEMA_TEXT: &str = include_str!("../../../schemas/binding.schema.json");
const TRIGGER_SCHEMA_TEXT: &str = include_str!("../../../schemas/trigger.schema.json");
const POLICY_SCHEMA_TEXT: &str = include_str!("../../../schemas/policy.schema.json");

static CAPSULE_SCHEMA: OnceLock<Value> = OnceLock::new();
static DEPLOYMENT_SCHEMA: OnceLock<Value> = OnceLock::new();
static BINDING_SCHEMA: OnceLock<Value> = OnceLock::new();
static TRIGGER_SCHEMA: OnceLock<Value> = OnceLock::new();
static POLICY_SCHEMA: OnceLock<Value> = OnceLock::new();

pub(crate) const fn schema_text(kind: ManifestKind) -> &'static str {
    match kind {
        ManifestKind::Capsule => CAPSULE_SCHEMA_TEXT,
        ManifestKind::Deployment => DEPLOYMENT_SCHEMA_TEXT,
        ManifestKind::Binding => BINDING_SCHEMA_TEXT,
        ManifestKind::Trigger => TRIGGER_SCHEMA_TEXT,
        ManifestKind::Policy => POLICY_SCHEMA_TEXT,
    }
}

pub(crate) fn validate_schema(
    kind: ManifestKind,
    instance: &Value,
    max_violations: usize,
) -> Vec<ManifestViolation> {
    let root = schema_document(kind);
    let mut violations = Vec::new();
    validate_node(
        root,
        instance,
        "$",
        root,
        &mut violations,
        max_violations.max(1),
    );
    violations.sort();
    violations.dedup();
    violations
}

fn schema_document(kind: ManifestKind) -> &'static Value {
    let (cell, text, name) = match kind {
        ManifestKind::Capsule => (&CAPSULE_SCHEMA, CAPSULE_SCHEMA_TEXT, "capsule"),
        ManifestKind::Deployment => (&DEPLOYMENT_SCHEMA, DEPLOYMENT_SCHEMA_TEXT, "deployment"),
        ManifestKind::Binding => (&BINDING_SCHEMA, BINDING_SCHEMA_TEXT, "binding"),
        ManifestKind::Trigger => (&TRIGGER_SCHEMA, TRIGGER_SCHEMA_TEXT, "trigger"),
        ManifestKind::Policy => (&POLICY_SCHEMA, POLICY_SCHEMA_TEXT, "policy"),
    };
    cell.get_or_init(|| {
        let schema: Value = serde_json::from_str(text)
            .unwrap_or_else(|error| panic!("embedded {name} schema is invalid JSON: {error}"));
        assert_supported_schema(&schema, "$schema");
        schema
    })
}

fn assert_supported_schema(schema: &Value, path: &str) {
    let object = schema
        .as_object()
        .unwrap_or_else(|| panic!("embedded schema node `{path}` must be an object"));
    for (keyword, value) in object {
        match keyword.as_str() {
            "$schema" | "$id" | "$ref" | "title" | "description" | "$comment"
            | "type" | "const" | "enum" | "required" | "default" | "uniqueItems" | "minLength"
            | "maxLength" | "pattern" | "minItems" | "maxItems" | "minProperties"
            | "maxProperties" | "minimum" | "maximum" => {}
            "$defs" | "properties" => {
                let children = value.as_object().unwrap_or_else(|| {
                    panic!("embedded schema keyword `{path}.{keyword}` must be an object")
                });
                for (name, child) in children {
                    assert_supported_schema(child, &format!("{path}.{keyword}.{name}"));
                }
            }
            "items" => assert_supported_schema(value, &format!("{path}.items")),
            "additionalProperties" if value.is_object() => {
                assert_supported_schema(value, &format!("{path}.additionalProperties"));
            }
            "additionalProperties" if value.is_boolean() => {}
            _ => panic!(
                "embedded schema keyword `{keyword}` at `{path}` is not implemented by the runtime evaluator"
            ),
        }
    }
}

fn validate_node(
    schema: &Value,
    instance: &Value,
    path: &str,
    root: &Value,
    violations: &mut Vec<ManifestViolation>,
    max_violations: usize,
) {
    if violations.len() >= max_violations {
        return;
    }

    if let Some(reference) = schema.get("$ref").and_then(Value::as_str) {
        let target = resolve_local_reference(root, reference);
        validate_node(target, instance, path, root, violations, max_violations);
        if violations.len() >= max_violations {
            return;
        }
    }

    if let Some(expected_type) = schema.get("type") {
        if !matches_type(expected_type, instance) {
            push_violation(
                violations,
                max_violations,
                path,
                "invalid-type",
                format!(
                    "expected {}, found {}",
                    display_expected_type(expected_type),
                    instance_type(instance)
                ),
            );
            return;
        }
    }

    if let Some(expected) = schema.get("const") {
        if !values_equal(instance, expected) {
            let code = if path == "$.apiVersion" {
                "unsupported-api-version"
            } else if path == "$.kind" {
                "unexpected-kind"
            } else {
                "invalid-value"
            };
            push_violation(
                violations,
                max_violations,
                path,
                code,
                format!("value must equal {}", display_json_value(expected)),
            );
        }
    }

    if let Some(allowed) = schema.get("enum").and_then(Value::as_array) {
        if !allowed
            .iter()
            .any(|candidate| values_equal(candidate, instance))
        {
            let code = if path == "$.kind" {
                "unexpected-kind"
            } else {
                "invalid-value"
            };
            push_violation(
                violations,
                max_violations,
                path,
                code,
                "value is not one of the schema-defined alternatives",
            );
        }
    }

    match instance {
        Value::Object(object) => {
            validate_object(schema, object, path, root, violations, max_violations);
        }
        Value::Array(items) => {
            validate_array(schema, items, path, root, violations, max_violations);
        }
        Value::String(value) => {
            validate_string(schema, value, path, violations, max_violations);
        }
        Value::Number(value) => {
            validate_number(schema, value, path, violations, max_violations);
        }
        Value::Null | Value::Bool(_) => {}
    }
}

fn validate_object(
    schema: &Value,
    object: &serde_json::Map<String, Value>,
    path: &str,
    root: &Value,
    violations: &mut Vec<ManifestViolation>,
    max_violations: usize,
) {
    if let Some(maximum) = schema.get("maxProperties").and_then(Value::as_u64) {
        if u64::try_from(object.len()).unwrap_or(u64::MAX) > maximum {
            push_violation(
                violations,
                max_violations,
                path,
                "too-many-properties",
                format!("object may contain at most {maximum} properties"),
            );
            return;
        }
    }

    if let Some(minimum) = schema.get("minProperties").and_then(Value::as_u64) {
        if u64::try_from(object.len()).unwrap_or(u64::MAX) < minimum {
            push_violation(
                violations,
                max_violations,
                path,
                "too-few-properties",
                format!("object must contain at least {minimum} properties"),
            );
        }
    }

    if let Some(required) = schema.get("required").and_then(Value::as_array) {
        for field in required.iter().filter_map(Value::as_str) {
            if !object.contains_key(field) {
                push_violation(
                    violations,
                    max_violations,
                    &child_path(path, field),
                    "missing-field",
                    format!("required field `{field}` is missing"),
                );
            }
            if violations.len() >= max_violations {
                return;
            }
        }
    }

    let properties = schema.get("properties").and_then(Value::as_object);
    if let Some(properties) = properties {
        for (field, field_schema) in properties {
            if let Some(value) = object.get(field) {
                validate_node(
                    field_schema,
                    value,
                    &child_path(path, field),
                    root,
                    violations,
                    max_violations,
                );
            }
            if violations.len() >= max_violations {
                return;
            }
        }
    }

    let known: BTreeSet<&str> = properties
        .map(|properties| properties.keys().map(String::as_str).collect())
        .unwrap_or_default();
    let additional = schema.get("additionalProperties");
    for (field, value) in object {
        if known.contains(field.as_str()) {
            continue;
        }
        match additional {
            Some(Value::Bool(false)) => push_violation(
                violations,
                max_violations,
                &child_path(path, field),
                "unknown-field",
                format!("field `{field}` is not defined by this schema version"),
            ),
            Some(Value::Object(_)) => validate_node(
                additional.expect("additionalProperties object is present"),
                value,
                &child_path(path, field),
                root,
                violations,
                max_violations,
            ),
            Some(Value::Bool(true)) | None => {}
            Some(_) => panic!("embedded schema has an invalid additionalProperties value"),
        }
        if violations.len() >= max_violations {
            return;
        }
    }
}

fn validate_array(
    schema: &Value,
    items: &[Value],
    path: &str,
    root: &Value,
    violations: &mut Vec<ManifestViolation>,
    max_violations: usize,
) {
    if let Some(minimum) = schema.get("minItems").and_then(Value::as_u64) {
        if u64::try_from(items.len()).unwrap_or(u64::MAX) < minimum {
            push_violation(
                violations,
                max_violations,
                path,
                "too-few-items",
                format!("array must contain at least {minimum} items"),
            );
        }
    }

    if let Some(maximum) = schema.get("maxItems").and_then(Value::as_u64) {
        if u64::try_from(items.len()).unwrap_or(u64::MAX) > maximum {
            push_violation(
                violations,
                max_violations,
                path,
                "too-many-items",
                format!("array may contain at most {maximum} items"),
            );
            return;
        }
    }

    if let Some(item_schema) = schema.get("items") {
        for (index, item) in items.iter().enumerate() {
            validate_node(
                item_schema,
                item,
                &format!("{path}[{index}]"),
                root,
                violations,
                max_violations,
            );
            if violations.len() >= max_violations {
                return;
            }
        }
    }

    if schema
        .get("uniqueItems")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        let mut seen = HashSet::with_capacity(items.len());
        for (index, item) in items.iter().enumerate() {
            if !seen.insert(canonical_value_key(item)) {
                push_violation(
                    violations,
                    max_violations,
                    &format!("{path}[{index}]"),
                    "duplicate-item",
                    "array items must be unique",
                );
            }
            if violations.len() >= max_violations {
                return;
            }
        }
    }
}

fn validate_string(
    schema: &Value,
    value: &str,
    path: &str,
    violations: &mut Vec<ManifestViolation>,
    max_violations: usize,
) {
    let character_count = value.chars().count();
    if let Some(minimum) = schema.get("minLength").and_then(Value::as_u64) {
        if u64::try_from(character_count).unwrap_or(u64::MAX) < minimum {
            push_violation(
                violations,
                max_violations,
                path,
                if minimum == 1 {
                    "empty-value"
                } else {
                    "string-too-short"
                },
                format!("string must contain at least {minimum} characters"),
            );
        }
    }
    if let Some(maximum) = schema.get("maxLength").and_then(Value::as_u64) {
        if u64::try_from(character_count).unwrap_or(u64::MAX) > maximum {
            push_violation(
                violations,
                max_violations,
                path,
                "string-too-long",
                format!("string may contain at most {maximum} characters"),
            );
        }
    }

    if let Some(pattern) = schema.get("pattern").and_then(Value::as_str) {
        let matches = match pattern {
            "^sha256:[a-fA-F0-9]{64}$" => is_sha256_digest(value),
            _ => panic!("embedded schema uses unsupported pattern `{pattern}`"),
        };
        if !matches {
            push_violation(
                violations,
                max_violations,
                path,
                "invalid-digest",
                "value must be a sha256: digest followed by exactly 64 hexadecimal characters",
            );
        }
    }
}

fn validate_number(
    schema: &Value,
    value: &Number,
    path: &str,
    violations: &mut Vec<ManifestViolation>,
    max_violations: usize,
) {
    if let Some(minimum) = schema.get("minimum").and_then(Value::as_number) {
        if compare_numbers(value, minimum) == Ordering::Less {
            push_violation(
                violations,
                max_violations,
                path,
                "out-of-range",
                format!("number must be at least {minimum}"),
            );
        }
    }
    if let Some(maximum) = schema.get("maximum").and_then(Value::as_number) {
        if compare_numbers(value, maximum) == Ordering::Greater {
            push_violation(
                violations,
                max_violations,
                path,
                "out-of-range",
                format!("number may be at most {maximum}"),
            );
        }
    }
}

fn matches_type(expected: &Value, instance: &Value) -> bool {
    match expected {
        Value::String(expected) => matches_single_type(expected, instance),
        Value::Array(expected) => expected
            .iter()
            .filter_map(Value::as_str)
            .any(|expected| matches_single_type(expected, instance)),
        _ => panic!("embedded schema has an invalid type declaration"),
    }
}

fn matches_single_type(expected: &str, instance: &Value) -> bool {
    match expected {
        "object" => instance.is_object(),
        "array" => instance.is_array(),
        "string" => instance.is_string(),
        "integer" => instance
            .as_number()
            .is_some_and(is_mathematical_integer),
        "number" => instance.is_number(),
        "boolean" => instance.is_boolean(),
        "null" => instance.is_null(),
        _ => panic!("embedded schema uses unsupported type `{expected}`"),
    }
}

fn values_equal(left: &Value, right: &Value) -> bool {
    match (left, right) {
        (Value::Number(left), Value::Number(right)) => {
            compare_numbers(left, right) == Ordering::Equal
        }
        (Value::Array(left), Value::Array(right)) => {
            left.len() == right.len()
                && left
                    .iter()
                    .zip(right)
                    .all(|(left, right)| values_equal(left, right))
        }
        (Value::Object(left), Value::Object(right)) => {
            left.len() == right.len()
                && left.iter().all(|(key, value)| {
                    right
                        .get(key)
                        .is_some_and(|right| values_equal(value, right))
                })
        }
        _ => left == right,
    }
}

fn canonical_value_key(value: &Value) -> String {
    let mut output = String::new();
    append_canonical_value_key(value, &mut output);
    output
}

fn append_canonical_value_key(value: &Value, output: &mut String) {
    match value {
        Value::Null => output.push('N'),
        Value::Bool(false) => output.push_str("B0"),
        Value::Bool(true) => output.push_str("B1"),
        Value::Number(number) => {
            output.push('D');
            output.push_str(&canonical_number_key(number));
            output.push(';');
        }
        Value::String(value) => {
            output.push('S');
            output.push_str(&value.len().to_string());
            output.push(':');
            output.push_str(value);
        }
        Value::Array(values) => {
            output.push('A');
            output.push_str(&values.len().to_string());
            output.push('[');
            for value in values {
                append_canonical_value_key(value, output);
            }
            output.push(']');
        }
        Value::Object(object) => {
            output.push('O');
            output.push_str(&object.len().to_string());
            output.push('{');
            let mut entries: Vec<_> = object.iter().collect();
            entries.sort_by(|left, right| left.0.cmp(right.0));
            for (key, value) in entries {
                output.push_str(&key.len().to_string());
                output.push(':');
                output.push_str(key);
                append_canonical_value_key(value, output);
            }
            output.push('}');
        }
    }
}

fn resolve_local_reference<'a>(root: &'a Value, reference: &str) -> &'a Value {
    let pointer = reference
        .strip_prefix('#')
        .unwrap_or_else(|| panic!("embedded schema contains non-local reference `{reference}`"));
    root.pointer(pointer)
        .unwrap_or_else(|| panic!("embedded schema reference `{reference}` does not resolve"))
}

fn push_violation(
    violations: &mut Vec<ManifestViolation>,
    maximum: usize,
    path: &str,
    code: &str,
    message: impl Into<String>,
) {
    if violations.len() < maximum {
        violations.push(ManifestViolation::new(path, code, message));
    }
}

fn child_path(parent: &str, field: &str) -> String {
    if is_simple_field(field) {
        format!("{parent}.{field}")
    } else {
        let quoted = serde_json::to_string(field).unwrap_or_else(|_| "\"?\"".to_owned());
        format!("{parent}[{quoted}]")
    }
}

fn is_simple_field(field: &str) -> bool {
    let mut characters = field.chars();
    let Some(first) = characters.next() else {
        return false;
    };
    (first == '_' || first.is_ascii_alphabetic())
        && characters.all(|character| character == '_' || character.is_ascii_alphanumeric())
}

fn display_expected_type(expected: &Value) -> String {
    match expected {
        Value::String(value) => value.clone(),
        Value::Array(values) => values
            .iter()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>()
            .join(" or "),
        _ => "a schema-defined type".to_owned(),
    }
}

fn instance_type(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Number(number) if is_mathematical_integer(number) => "integer",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

fn display_json_value(value: &Value) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "<unprintable>".to_owned())
}

pub(crate) fn is_sha256_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..].bytes().all(|byte| byte.is_ascii_hexdigit())
}
