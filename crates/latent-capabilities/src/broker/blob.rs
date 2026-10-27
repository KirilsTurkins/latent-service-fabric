//! Typed immutable-blob port. References and numbers carry no tenant authority.
use super::io::IoFuture;
use super::{
    io::{IoBuffer, IoOutputCopy, PreparedIoCopy},
    pools::PoolCall,
    CapabilitySession,
};
use latent_core::{PlatformError, PlatformErrorCode};

pub const BLOB_CAPABILITY: &str = "latent:blob/blob@0.2.0";
pub type BlobFuture<'a, T> = IoFuture<'a, Result<T, BlobError>>;

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
    copy: Option<PreparedIoCopy>,
    owner: Option<PoolCall>,
}
impl BlobChunk {
    pub fn new(data: IoBuffer, copy: PreparedIoCopy, owner: PoolCall) -> Result<Self, BlobError> {
        // Identity checks precede retained-output mutation and any copy. A
        // public io_mut swap cannot pair another Request with these bytes.
        copy.check_blob(&data, &owner)?;
        Ok(Self {
            data: data.retain()?,
            copy: Some(copy),
            owner: Some(owner),
        })
    }
    /// Move the one original reservation and affine call into the physical
    /// copy owner. The source buffer independently retains Operation/Request.
    pub fn copy_bytes(&mut self) -> Result<IoOutputCopy, BlobError> {
        let copy = self.copy.take().ok_or(BlobError::InvalidState)?;
        let owner = self.owner.take().expect("one checked blob copy owner");
        copy.finish_blob(&self.data, owner).map_err(BlobError::from)
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
    /// Borrowed guest ingress. Implementations prepay an actual input copy from
    /// their original admission before materialization. The independent slice
    /// lifetime cannot escape into the returned writer-borrowing future.
    fn write_from<'a>(
        &'a mut self,
        offset: u64,
        source: &[u8],
    ) -> Result<BlobFuture<'a, u64>, BlobError>;
    fn seal(self: Box<Self>) -> Result<BlobFuture<'static, BlobSeal>, BlobError>;
}
pub trait BlobReader: Send {
    fn read(&mut self, offset: u64, length: u32) -> Result<BlobFuture<'_, BlobChunk>, BlobError>;
}
