use super::{corrupt, exhausted, Result, Transport};
use latent_core::PlatformErrorCode;
use reqwest::{header, Response};

impl Transport {
    pub(crate) async fn read_body(
        &self,
        mut response: Response,
        maximum: usize,
        expected: Option<u64>,
    ) -> Result<Vec<u8>> {
        if response
            .content_length()
            .is_some_and(|size| size > maximum as u64)
        {
            return Err(exhausted("oci-response-byte-limit"));
        }
        if let (Some(actual), Some(expected)) = (response.content_length(), expected) {
            if actual != expected {
                return Err(corrupt("oci-response-length-mismatch"));
            }
        }
        let capacity = usize::try_from(response.content_length().unwrap_or(0).min(maximum as u64))
            .map_err(|_| exhausted("oci-response-byte-limit"))?;
        let mut bytes = Vec::new();
        bytes
            .try_reserve_exact(capacity)
            .map_err(|_| exhausted("oci-response-allocation-limit"))?;
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|error| super::transport::network_error(&error))?
        {
            let length = bytes
                .len()
                .checked_add(chunk.len())
                .filter(|value| *value <= maximum)
                .ok_or_else(|| exhausted("oci-response-byte-limit"))?;
            if length > bytes.capacity() {
                bytes
                    .try_reserve_exact(length - bytes.len())
                    .map_err(|_| exhausted("oci-response-allocation-limit"))?;
            }
            bytes.extend_from_slice(&chunk);
        }
        if expected.is_some_and(|size| size != bytes.len() as u64) {
            return Err(corrupt("oci-response-length-mismatch"));
        }
        Ok(bytes)
    }
}

pub(super) fn headers(response: &Response) -> Result<()> {
    let mut bytes = 0_usize;
    if response.headers().len() > 100 {
        return Err(exhausted("oci-response-header-limit"));
    }
    for (key, value) in response.headers() {
        bytes = bytes
            .checked_add(key.as_str().len() + value.as_bytes().len())
            .filter(|value| *value <= 16 * 1024)
            .ok_or_else(|| exhausted("oci-response-header-limit"))?;
    }
    for name in [
        "content-type",
        "content-length",
        "content-encoding",
        "location",
        "docker-content-digest",
        "oci-subject",
    ] {
        if response.headers().get_all(name).iter().count() > 1 {
            return Err(corrupt("oci-ambiguous-response-header"));
        }
    }
    if response
        .headers()
        .get_all(header::CONTENT_ENCODING)
        .iter()
        .any(|value| value != "identity")
    {
        return Err(crate::error(
            PlatformErrorCode::InvalidArgument,
            "oci-content-encoding-unsupported",
        ));
    }
    Ok(())
}
