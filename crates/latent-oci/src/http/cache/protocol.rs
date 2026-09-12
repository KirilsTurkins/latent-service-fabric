use super::super::{corrupt, transport, HttpOciRegistry, Result};
use crate::OciDescriptor;
use reqwest::{header::CONTENT_LENGTH, Method, StatusCode};
use tokio::time::Instant;

impl HttpOciRegistry {
    pub(super) async fn authorize_cached_blob(
        &self,
        descriptor: &OciDescriptor,
        deadline: Instant,
    ) -> Result<bool> {
        let url = self
            .transport
            .endpoint
            .url(&format!("blobs/{}", descriptor.digest))?;
        let response = self
            .transport
            .send(Method::HEAD, url, None, None, deadline)
            .await?;
        if matches!(
            response.status(),
            StatusCode::METHOD_NOT_ALLOWED | StatusCode::NOT_IMPLEMENTED
        ) {
            return Ok(false);
        }
        transport::expect_status(&response, &[StatusCode::OK])?;
        transport::verify_digest_header(response.headers(), &descriptor.digest)?;
        // Response::content_length on HEAD may describe its empty transport body;
        // the raw header is the advertised blob length. Require an exact value.
        let size = response
            .headers()
            .get(CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<u64>().ok())
            .ok_or_else(|| corrupt("oci-cached-head-length-missing"))?;
        if size != descriptor.size_bytes {
            return Err(corrupt("oci-cached-head-length-mismatch"));
        }
        Ok(true)
    }
}
