//! Exact package signatures and bounded, current publisher trust decisions.
//!
//! A publisher proof does not establish tenant authority, catalog admission,
//! guest validity, routability or permission to load native code.

#![forbid(unsafe_code)]

mod crypto;
mod error;
mod evidence;
mod format;
mod keys;
mod limits;
mod policy;
mod signer;
mod subject;
mod verify;

pub use error::{SignatureError, SignatureFailure, SignatureResult};
pub use evidence::{SignatureEvidence, SignatureEvidenceRef};
pub use format::{
    inspect_signature, SignatureValidity, UnverifiedSignature, SIGNATURE_PAYLOAD_TYPE,
};
pub use keys::{generate_signing_key, GeneratedSigningKey};
pub use limits::SignatureLimits;
pub use policy::{
    PublisherKeyConfig, PublisherPolicy, PublisherPolicyConfig, PublisherTrust, RevocationSnapshot,
    RevocationSnapshotConfig, TrustStateId,
};
pub use signer::LocalSigner;
pub use subject::PackageSigningSubject;
pub use verify::{PublisherVerifier, VerifiedPackageSignature};

/// The v1 signature profile's maximum lifetime, in seconds.
pub const MAX_SIGNATURE_LIFETIME_SECONDS: u64 = 31 * 24 * 60 * 60;
/// Maximum lifetime of a reusable positive proof, without extending its evidence.
pub const MAX_PROOF_AGE_SECONDS: u64 = 60 * 60;

use latent_core::{Metadata, PackageDigest};

/// Untrusted provenance claims; a separate builder verifier must authenticate them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProvenanceStatement {
    pub subject: PackageDigest,
    pub builder: String,
    pub source_repository: Option<String>,
    pub source_revision: Option<String>,
    pub build_parameters: Metadata,
    pub predicate_type: String,
    pub predicate: Vec<u8>,
}

/// Untrusted association metadata, without any SBOM authenticity assertion.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SbomReference {
    pub subject: PackageDigest,
    pub media_type: String,
    pub digest: String,
}
