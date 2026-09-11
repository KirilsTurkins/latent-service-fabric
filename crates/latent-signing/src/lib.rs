//! Signature, provenance, attestation, and publisher trust interfaces.

#![forbid(unsafe_code)]

use latent_core::{BoxFuture, Metadata, PackageDigest, PlatformError, PublisherId};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SignatureEnvelope {
    /// The immutable package manifest identity, not its component-only release digest.
    pub subject: PackageDigest,
    pub algorithm: String,
    pub signature: Vec<u8>,
    pub certificate_chain: Vec<Vec<u8>>,
    pub key_hint: Option<String>,
    pub annotations: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProvenanceStatement {
    /// The package whose complete content association the provenance describes.
    pub subject: PackageDigest,
    pub builder: String,
    pub source_repository: Option<String>,
    pub source_revision: Option<String>,
    pub build_parameters: Metadata,
    pub predicate_type: String,
    pub predicate: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SbomReference {
    /// The package associated with this SBOM; the association alone is not trust proof.
    pub subject: PackageDigest,
    pub media_type: String,
    pub digest: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublisherIdentity {
    pub id: PublisherId,
    pub display_name: Option<String>,
    pub claims: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerificationReport {
    pub trusted: bool,
    pub publisher: Option<PublisherIdentity>,
    pub signature_valid: bool,
    pub provenance_valid: bool,
    pub sbom_present: bool,
    pub reasons: Vec<String>,
}

pub trait SignatureVerifier: Send + Sync {
    fn verify<'a>(
        &'a self,
        envelope: &'a SignatureEnvelope,
    ) -> BoxFuture<'a, Result<VerificationReport, PlatformError>>;
}

pub trait AttestationVerifier: Send + Sync {
    fn verify_provenance<'a>(
        &'a self,
        statement: &'a ProvenanceStatement,
    ) -> BoxFuture<'a, Result<VerificationReport, PlatformError>>;
}

pub trait TrustPolicy: Send + Sync {
    fn evaluate(&self, report: &VerificationReport) -> Result<(), PlatformError>;
}
