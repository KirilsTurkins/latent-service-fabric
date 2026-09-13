use crate::error;
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use reqwest::Url;

// Preserve the registry's opaque upload state verbatim. Parsing and rewriting
// all query pairs would normalize percent escapes that the server may sign.
pub(super) fn with_digest(
    location: &Url,
    digest: &ArtifactBlobDigest,
    max_url_bytes: usize,
) -> Result<Url, PlatformError> {
    if location.query_pairs().any(|(key, _)| key == "digest") {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "oci-upload-location-has-digest",
        ));
    }
    let query = match location.query() {
        Some(query) if !query.is_empty() => format!("{query}&digest={}", digest.as_str()),
        _ => format!("digest={}", digest.as_str()),
    };
    let mut target = location.clone();
    target.set_query(Some(&query));
    if target.as_str().len() > max_url_bytes {
        return Err(error(
            PlatformErrorCode::ResourceExhausted,
            "oci-upload-location-limit",
        ));
    }
    Ok(target)
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_artifacts::package::artifact_blob_digest;

    #[test]
    fn opaque_upload_query_remains_byte_exact() {
        let location = Url::parse(
            "https://registry.example/v2/site/blobs/uploads/id?_state=a%2fb%2B%3D&empty=&x=1+2",
        )
        .unwrap();
        let digest = artifact_blob_digest(b"payload");
        let target = with_digest(&location, &digest, 4096).unwrap();
        assert_eq!(
            target.query().unwrap(),
            format!("_state=a%2fb%2B%3D&empty=&x=1+2&digest={}", digest.as_str())
        );
        assert!(with_digest(&location, &digest, location.as_str().len()).is_err());
        let duplicate =
            Url::parse("https://registry.example/v2/site/blobs/uploads/id?%64igest=sha256%3Aother")
                .unwrap();
        assert!(with_digest(&duplicate, &digest, 4096).is_err());
    }
}
