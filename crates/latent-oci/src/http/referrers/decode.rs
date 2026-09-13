use crate::{error, OciDescriptor};
use latent_artifacts::package::{validate_package_json, PackageLimits, OCI_MANIFEST_MEDIA_TYPE};
use latent_core::{Metadata, PackageDigest, PlatformError, PlatformErrorCode};
use serde::Deserialize;

pub(super) const INDEX_MEDIA_TYPE: &str = "application/vnd.oci.image.index.v1+json";

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Index {
    schema_version: u32,
    media_type: String,
    manifests: Vec<Descriptor>,
    #[serde(default)]
    annotations: Metadata,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Descriptor {
    media_type: String,
    digest: String,
    size: u64,
    #[serde(default)]
    artifact_type: Option<String>,
    #[serde(default)]
    annotations: Metadata,
}

pub(super) fn index(
    bytes: &[u8],
    limits: PackageLimits,
    max_entries: usize,
) -> Result<Vec<OciDescriptor>, PlatformError> {
    // This checks duplicate keys, lexical integer form and all resource bounds
    // before serde constructs the closed wire model. No null optionals survive.
    validate_package_json(bytes, limits)?;
    let index: Index =
        serde_json::from_slice(bytes).map_err(|_| invalid("invalid-oci-referrers"))?;
    if index.schema_version != 2 || index.media_type != INDEX_MEDIA_TYPE {
        return Err(invalid("invalid-oci-referrers-envelope"));
    }
    annotations(&index.annotations, limits)?;
    if index.manifests.len() > max_entries {
        return Err(error(
            PlatformErrorCode::ResourceExhausted,
            "oci-referrer-entry-limit",
        ));
    }
    index
        .manifests
        .into_iter()
        .map(|value| descriptor(value, limits))
        .collect()
}

fn descriptor(value: Descriptor, limits: PackageLimits) -> Result<OciDescriptor, PlatformError> {
    if !matches!(
        value.media_type.as_str(),
        OCI_MANIFEST_MEDIA_TYPE | INDEX_MEDIA_TYPE
    ) || value.digest.parse::<PackageDigest>().is_err()
        || value.size == 0
        || value.size > limits.max_document_bytes as u64
    {
        return Err(invalid("invalid-oci-referrer-descriptor"));
    }
    if let Some(kind) = &value.artifact_type {
        media_type(kind, limits.max_string_bytes)?;
    }
    annotations(&value.annotations, limits)?;
    Ok(OciDescriptor {
        media_type: value.media_type,
        digest: value.digest,
        size_bytes: value.size,
        annotations: value.annotations,
        artifact_type: value.artifact_type,
    })
}

pub(crate) fn media_type(value: &str, maximum: usize) -> Result<(), PlatformError> {
    let Some((left, right)) = value.split_once('/') else {
        return Err(invalid("invalid-oci-artifact-type"));
    };
    let token = |part: &str| {
        part.as_bytes()
            .first()
            .is_some_and(u8::is_ascii_alphanumeric)
            && part
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"!#$&^_.+-".contains(&byte))
    };
    if value.len() > maximum || !token(left) || !token(right) {
        return Err(invalid("invalid-oci-artifact-type"));
    }
    Ok(())
}

fn annotations(values: &Metadata, limits: PackageLimits) -> Result<(), PlatformError> {
    if values.len() > limits.max_annotations {
        return Err(error(
            PlatformErrorCode::ResourceExhausted,
            "oci-referrer-annotation-limit",
        ));
    }
    if values.keys().any(String::is_empty) {
        return Err(invalid("invalid-oci-referrer-annotations"));
    }
    Ok(())
}

fn invalid(reason: &'static str) -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, reason)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid() -> String {
        format!(
            r#"{{"schemaVersion":2,"mediaType":"{INDEX_MEDIA_TYPE}","manifests":[{{"mediaType":"{OCI_MANIFEST_MEDIA_TYPE}","digest":"sha256:{}","size":10,"artifactType":"application/vnd.latent.signature.v1","annotations":{{"example":"value"}}}}]}}"#,
            "a".repeat(64)
        )
    }

    #[test]
    fn index_metadata_is_bounded_before_typed_discovery() {
        let limits = PackageLimits::default();
        let bytes = valid();
        let result = index(bytes.as_bytes(), limits, 1).unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(
            result[0].artifact_type.as_deref(),
            Some("application/vnd.latent.signature.v1")
        );
        assert_eq!(
            index(bytes.as_bytes(), limits, 0).unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
        for changed in [
            bytes.replace("\"size\":10", "\"size\":1e1"),
            bytes.replace("\"size\":10", "\"size\":10,\"size\":10"),
            bytes.replace(
                "\"example\":\"value\"",
                "\"example\":\"value\",\"example\":\"again\"",
            ),
            bytes.replace("\"size\":10", "\"size\":262145"),
            bytes.replace("\"size\":10", "\"size\":0"),
            bytes.replace("\"size\":10", "\"size\":10,\"urls\":[]"),
            bytes.replace("\"application/vnd.latent.signature.v1\"", "null"),
            bytes.replace("application/vnd.latent.signature.v1", "./+"),
        ] {
            assert!(index(changed.as_bytes(), limits, 1).is_err());
        }
    }
}
