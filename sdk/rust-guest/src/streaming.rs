//! Owned HTTP resources with explicit asynchronous operations. Dropping an upload
//! or body aborts its I/O through the generated resource destructor; held chunks
//! keep their own charge. No operation retries or renews the activation deadline.
use crate::bindings::streaming as raw;
pub use raw::{Header, HttpError, Method, Request};

#[must_use = "finish or abort the upload; dropping it aborts I/O"]
pub struct Upload(raw::Upload);

impl Upload {
    pub async fn open(request: Request) -> Result<Self, HttpError> {
        raw::open(request).await.map(Self)
    }

    pub async fn write(&mut self, bytes: Vec<u8>) -> Result<(), HttpError> {
        raw::write(&self.0, bytes).await
    }

    pub async fn finish(self) -> Result<Response, HttpError> {
        let response = raw::finish(self.0).await?;
        Ok(Response {
            status: response.status,
            headers: response.headers,
            body_media_type: response.body_media_type,
            body: Body(response.body),
        })
    }

    pub async fn abort(self) -> Result<(), HttpError> {
        raw::abort_upload(self.0).await
    }
}

pub struct Response {
    pub status: u16,
    pub headers: Vec<Header>,
    pub body_media_type: Option<String>,
    pub body: Body,
}

#[must_use = "read or abort the body; dropping it aborts I/O"]
pub struct Body(raw::Body);

impl Body {
    /// `None` means verified EOF; an incomplete response remains a typed error.
    pub async fn read(&mut self, maximum_bytes: u32) -> Result<Option<Chunk>, HttpError> {
        raw::read(&self.0, maximum_bytes)
            .await
            .map(|chunk| chunk.map(Chunk))
    }

    /// Read once, after verified EOF. Premature or repeated calls retain the
    /// host's `InvalidState` error.
    pub async fn trailers(&mut self) -> Result<Vec<Header>, HttpError> {
        raw::trailers(&self.0).await
    }

    pub async fn abort(self) -> Result<(), HttpError> {
        raw::abort_body(self.0).await
    }
}

/// A host resource, released by generated Component Model `Drop`.
pub struct Chunk(raw::Chunk);

impl Chunk {
    pub async fn bytes(self) -> Result<Vec<u8>, HttpError> {
        raw::chunk_bytes(&self.0).await
    }
}
