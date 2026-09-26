//! Activation-owned blob handles. Explicitly close readers and close or seal
//! writers. Abandoned handles remain charged until the host closes the activation;
//! `Drop` cannot perform this asynchronous operation and starts no hidden task.
use crate::bindings::blob as raw;
pub use raw::{BlobError, BlobReference};

#[must_use = "close or seal the writer; abandonment retains its activation charge"]
pub struct Writer(u64);

impl Writer {
    pub async fn create(media_type: String, expected_size: Option<u64>) -> Result<Self, BlobError> {
        raw::create(media_type, expected_size).await.map(Self)
    }

    /// Writes are sequential. Preserve the host's returned offset and typed error.
    pub async fn write(&mut self, offset: u64, bytes: Vec<u8>) -> Result<u64, BlobError> {
        raw::write(self.0, offset, bytes).await
    }

    /// Consumes the writer on success or failure; an uncertain result is not retried.
    pub async fn seal(self) -> Result<BlobReference, BlobError> {
        raw::seal(self.0).await
    }

    pub async fn close(self) -> Result<bool, BlobError> {
        raw::close(self.0).await
    }
}

#[must_use = "close the reader; abandonment retains its activation charge"]
pub struct Reader(u64);

impl Reader {
    pub async fn open(reference: BlobReference) -> Result<Self, BlobError> {
        raw::open(reference).await.map(Self)
    }

    pub async fn read(&mut self, offset: u64, length: u32) -> Result<Chunk, BlobError> {
        raw::read(self.0, offset, length).await.map(Chunk)
    }

    pub async fn close(self) -> Result<bool, BlobError> {
        raw::close(self.0).await
    }
}

/// A host resource, released by generated Component Model `Drop`.
pub struct Chunk(raw::Chunk);

impl Chunk {
    /// Materialize once and release the host resource when this call completes.
    /// The returned guest allocation remains owned by the caller.
    pub async fn bytes(self) -> Result<Vec<u8>, BlobError> {
        raw::chunk_bytes(&self.0).await
    }
}
