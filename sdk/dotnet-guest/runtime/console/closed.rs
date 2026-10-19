//! Existing closed stdio selection; a log declaration is required for a sink.
use super::exports::wasi::io;
pub struct Stream;
pub fn stdout() -> Option<Stream> {
    None
}
pub fn stderr() -> Option<Stream> {
    None
}
impl Stream {
    pub fn check_write(&self) -> Result<u64, io::streams::StreamError> {
        Err(io::streams::StreamError::Closed)
    }
    pub fn write(&self, _contents: Vec<u8>) -> Result<(), io::streams::StreamError> {
        Err(io::streams::StreamError::Closed)
    }
    pub fn flush(&self) -> Result<(), io::streams::StreamError> {
        Err(io::streams::StreamError::Closed)
    }
}
