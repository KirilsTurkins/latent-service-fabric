use super::{domain, proto, Failure, Value};
use serde_json::json;
#[cfg(test)]
mod tests;
pub(super) fn invalid() -> Failure {
    Failure::protocol(
        "invalid-capability-policy-response",
        "The node returned an invalid capability policy response.",
    )
}
fn id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|v| v.is_ascii_alphanumeric() || b"-_.:/@".contains(&v))
}
pub(super) fn receipt(
    value: &proto::CapabilityPolicyOperation,
    tenant: &str,
    operation: Option<&str>,
) -> Result<Value, Failure> {
    if value.tenant != tenant
        || !id(&value.id)
        || !id(&value.operation_id)
        || value.generation < 2
        || operation.is_some_and(|v| v != value.operation_id)
        || !super::super::super::canonical_digest(&value.content_digest)
        || !matches!(
            proto::CapabilityPolicyRecordKind::try_from(value.record_kind),
            Ok(proto::CapabilityPolicyRecordKind::Policy
                | proto::CapabilityPolicyRecordKind::ProviderBinding)
        )
    {
        return Err(invalid());
    }
    Ok(
        json!({"operationId":value.operation_id,"tenant":value.tenant,"id":value.id,"recordKind":kind_name(value.record_kind)?,
        "generation":value.generation.to_string(),"contentDigest":value.content_digest,"revoked":value.revoked}),
    )
}
pub(super) fn record(
    value: &proto::Policy,
    tenant: &str,
    kind: i32,
    expected: Option<&str>,
) -> Result<Value, Failure> {
    if value.record_kind != kind
        || !id(&value.id)
        || expected.is_some_and(|v| v != value.id)
        || value.generation < 2
        || !super::super::super::canonical_digest(&value.content_digest)
        || value.document.len() > domain::MAX_DOCUMENT_BYTES
    {
        return Err(invalid());
    }
    let metadata = value.metadata.as_ref().ok_or_else(invalid)?;
    if metadata.name != value.id
        || metadata.tenant.as_deref() != Some(tenant)
        || metadata.namespace.is_some()
        || !metadata.labels.is_empty()
        || !metadata.annotations.is_empty()
    {
        return Err(invalid());
    }
    let expected_language = match proto::CapabilityPolicyRecordKind::try_from(kind) {
        Ok(proto::CapabilityPolicyRecordKind::Policy) => domain::LANGUAGE,
        Ok(proto::CapabilityPolicyRecordKind::ProviderBinding) => domain::PROVIDER_BINDING_LANGUAGE,
        _ => return Err(invalid()),
    };
    if value.language != expected_language {
        return Err(invalid());
    }
    let document = if value.revoked {
        if !value.document.is_empty() {
            return Err(invalid());
        }
        Value::Null
    } else {
        validate_document(value, tenant)?;
        serde_json::from_str(&value.document).map_err(|_| invalid())?
    };
    Ok(
        json!({"id":value.id,"tenant":tenant,"recordKind":kind_name(kind)?,"language":value.language,"generation":value.generation.to_string(),
        "contentDigest":value.content_digest,"revoked":value.revoked,"document":document}),
    )
}
fn validate_document(value: &proto::Policy, tenant: &str) -> Result<(), Failure> {
    let (actual, digest, canonical) =
        match proto::CapabilityPolicyRecordKind::try_from(value.record_kind) {
            Ok(proto::CapabilityPolicyRecordKind::Policy) => {
                let parsed = domain::CapabilityPolicy::parse(value.document.as_bytes())
                    .map_err(|_| invalid())?;
                (
                    parsed.tenant().to_owned(),
                    parsed.digest().to_owned(),
                    parsed.canonical() == value.document.as_bytes(),
                )
            }
            Ok(proto::CapabilityPolicyRecordKind::ProviderBinding) => {
                let parsed = domain::ProviderBinding::parse(value.document.as_bytes())
                    .map_err(|_| invalid())?;
                (
                    parsed.tenant().to_owned(),
                    parsed.digest().to_owned(),
                    parsed.canonical() == value.document.as_bytes(),
                )
            }
            _ => return Err(invalid()),
        };
    if actual != tenant || digest != value.content_digest || !canonical {
        return Err(invalid());
    }
    Ok(())
}
fn kind_name(value: i32) -> Result<&'static str, Failure> {
    match proto::CapabilityPolicyRecordKind::try_from(value) {
        Ok(proto::CapabilityPolicyRecordKind::Policy) => Ok("policy"),
        Ok(proto::CapabilityPolicyRecordKind::ProviderBinding) => Ok("provider-binding"),
        _ => Err(invalid()),
    }
}
