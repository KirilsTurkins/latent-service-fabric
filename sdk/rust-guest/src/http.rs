//! One bounded buffered request. The original typed error, including uncertain,
//! is preserved. An idempotency key never enables a retry.
pub use crate::bindings::http::{Header, HttpError, Method, Request, Response};
pub async fn send(request: Request) -> Result<Response, HttpError> {
    crate::bindings::http::send(request).await
}
