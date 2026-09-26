//! Borrow secret bytes while owned; erase this guest allocation when dropped.
//! The host cannot erase copies the application chooses to make.
use crate::bindings::secrets as raw;
pub use raw::SecretError;
use zeroize::Zeroizing;

pub struct Secret {
    bytes: Zeroizing<Vec<u8>>,
    media_type: String,
    version: Option<String>,
    expires_at_unix_millis: Option<u64>,
}
impl Secret {
    pub fn read(reference: &str) -> Result<Self, SecretError> {
        let value = raw::read(reference)?;
        Ok(Self {
            bytes: Zeroizing::new(value.bytes),
            media_type: value.media_type,
            version: value.version,
            expires_at_unix_millis: value.expires_at_unix_millis,
        })
    }
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    #[must_use]
    pub fn media_type(&self) -> &str {
        &self.media_type
    }
    #[must_use]
    pub fn version(&self) -> Option<&str> {
        self.version.as_deref()
    }
    #[must_use]
    pub fn expires_at_unix_millis(&self) -> Option<u64> {
        self.expires_at_unix_millis
    }
}
