//! Typed immutable-blob port. References and numbers carry no tenant authority.
use super::{
    io::{IoBuffer, IoMemory},
    pools::PoolCall,
    CapabilitySession,
};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};

pub const BLOB_CAPABILITY: &str = "latent:blob/blob@0.2.0";
pub type BlobFuture<'a, T> = BoxFuture<'a, Result<T, BlobError>>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BlobError {
    NotFound,
    PermissionDenied,
    InvalidRange,
    InvalidState,
    ChecksumMismatch,
    BudgetExhausted,
    Unavailable,
    Uncertain,
    DeadlineExceeded,
    Cancelled,
}
impl From<PlatformError> for BlobError {
    fn from(error: PlatformError) -> Self {
        match error.code {
            PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
                Self::PermissionDenied
            }
            PlatformErrorCode::ResourceExhausted | PlatformErrorCode::AdmissionRejected => {
                Self::BudgetExhausted
            }
            PlatformErrorCode::InvalidArgument => Self::InvalidRange,
            PlatformErrorCode::DeadlineExceeded => Self::DeadlineExceeded,
            PlatformErrorCode::Cancelled => Self::Cancelled,
            _ => Self::Unavailable,
        }
    }
}
#[derive(Clone, PartialEq, Eq)]
pub struct BlobReference {
    pub digest: String,
    pub size: u64,
    pub media_type: String,
}
pub struct BlobSeal {
    pub reference: BlobReference,
    /// Retain through the single canonical reference lowering.
    pub owner: PoolCall,
}
/// A single bounded range and its prepaid guest copy, including an empty range.
/// The host resource permits exactly one materialization before Drop.
pub struct BlobChunk {
    data: IoBuffer,
    _copy: IoMemory,
    _owner: PoolCall,
}
impl BlobChunk {
    pub fn new(data: IoBuffer, copy: IoMemory, owner: PoolCall) -> Result<Self, BlobError> {
        Ok(Self {
            data: data.retain()?,
            _copy: copy,
            _owner: owner,
        })
    }
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        self.data.bytes()
    }
}
pub trait BlobInvoker: Send + Sync {
    fn create(
        &self,
        session: &CapabilitySession,
        media_type: String,
        expected_size: Option<u64>,
    ) -> Result<BlobFuture<'static, Box<dyn BlobWriter>>, BlobError>;
    fn open(
        &self,
        session: &CapabilitySession,
        reference: BlobReference,
    ) -> Result<BlobFuture<'static, Box<dyn BlobReader>>, BlobError>;
}
pub trait BlobWriter: Send {
    /// Admission precedes future allocation. An accepted failure abandons the
    /// writer; dropping the future does not refund a still-running physical job.
    fn write(&mut self, offset: u64, bytes: Vec<u8>) -> Result<BlobFuture<'_, u64>, BlobError>;
    fn seal(self: Box<Self>) -> Result<BlobFuture<'static, BlobSeal>, BlobError>;
}
pub trait BlobReader: Send {
    fn read(&mut self, offset: u64, length: u32) -> Result<BlobFuture<'_, BlobChunk>, BlobError>;
}
