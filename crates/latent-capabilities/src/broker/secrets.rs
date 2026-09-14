//! Explicit plaintext disclosure is separate from opaque provider credentials.
use super::{io::IoMemory, pools::PoolCall, CapabilitySession};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};

pub const SECRETS_CAPABILITY: &str = "latent:secrets/reader@0.1.0";
pub type SecretFuture = BoxFuture<'static, Result<Box<dyn SecretDisclosure>, SecretError>>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SecretError {
    NotFound,
    PermissionDenied,
    Expired,
    Unavailable,
}
impl From<PlatformError> for SecretError {
    fn from(value: PlatformError) -> Self {
        match value.code {
            PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
                Self::PermissionDenied
            }
            _ => Self::Unavailable,
        }
    }
}

/// Borrowed only during a checked, bounded copy into the canonical guest result.
/// No Debug or serialization implementation may expose this material.
pub struct SecretView<'a> {
    pub bytes: &'a [u8],
    pub media_type: &'a str,
    pub version: &'a str,
    pub expires_at_unix_millis: Option<u64>,
}
/// Retain both the admitted result and the extra canonical copy until the Store
/// is destroyed. Contains no secret material and offers no authority constructor.
pub struct SecretLowering {
    _call: PoolCall,
    _copy: IoMemory,
}
impl SecretLowering {
    #[must_use]
    pub fn new(call: PoolCall, copy: IoMemory) -> Self {
        Self {
            _call: call,
            _copy: copy,
        }
    }
}
pub trait SecretDisclosure: Send {
    /// Consumes a single prepaid disclosure. The implementation rechecks its
    /// current generation, expiry and cancellation at this copy boundary. The
    /// returned call remains charged until canonical lowering/Store destruction.
    fn disclose(
        self: Box<Self>,
        copy: &mut dyn FnMut(SecretView<'_>),
    ) -> Result<SecretLowering, SecretError>;
}
pub trait SecretInvoker: Send + Sync {
    fn read(
        &self,
        session: &CapabilitySession,
        reference: String,
    ) -> Result<SecretFuture, SecretError>;
}

/// Explicit trusted provider scope, checked against the actual tenant and
/// destination by the transport. It has no guest resource or plaintext API.
pub struct CredentialScope {
    pub tenant: latent_core::TenantId,
    pub provider_id: String,
    pub origin: latent_policy::capability::HttpOrigin,
}
pub trait ProviderCredential: Send + Sync {
    fn scope(&self) -> &CredentialScope;
    fn reference(&self) -> &str;
    /// Trusted adapters copy at most their separately prepaid header/signing
    /// limit. Resolving a provider credential never authorizes a guest read.
    fn with_current_value(
        &self,
        use_value: &mut dyn FnMut(&[u8]) -> Result<(), SecretError>,
    ) -> Result<(), SecretError>;
}
