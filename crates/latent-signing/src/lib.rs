//! Exact package signatures, build provenance and bounded current trust decisions.
//!
//! Independent publisher and builder proofs do not establish tenant authority,
//! catalog admission, guest validity, routability or permission to load native code.

#![forbid(unsafe_code)]

mod admission;
mod builder_policy;
mod builder_verify;
mod crypto;
mod dsse;
mod error;
mod evidence;
mod format;
mod keys;
mod limits;
mod policy;
mod provenance;
mod signer;
mod subject;
mod verify;

pub use admission::{verify_current_supply_chain_evidence, VerifiedSupplyChainEvidence};
pub use builder_policy::{
    BuilderKeyConfig, BuilderPolicy, BuilderPolicyConfig, BuilderRequirement,
    BuilderRevocationSnapshot, BuilderRevocationSnapshotConfig, BuilderTrust, BuilderTrustStateId,
};
pub use builder_verify::{BuilderVerifier, VerifiedBuildProvenance};
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
pub use provenance::{
    decode_build_observation, inspect_provenance, BuildMaterial, BuildObservation, BuildParameters,
    BuildSource, LocalBuilderSigner, ProvenanceEvidence, ProvenanceEvidenceRef, ProvenanceLimits,
    UnverifiedProvenance, PROVENANCE_BUILD_TYPE, PROVENANCE_PAYLOAD_TYPE,
    PROVENANCE_PREDICATE_TYPE,
};
pub use signer::LocalSigner;
pub use subject::PackageSigningSubject;
pub use verify::{PublisherVerifier, VerifiedPackageSignature};

/// The v1 signature profile's maximum lifetime, in seconds.
pub const MAX_SIGNATURE_LIFETIME_SECONDS: u64 = 31 * 24 * 60 * 60;
/// Maximum lifetime of a reusable positive proof, without extending its evidence.
pub const MAX_PROOF_AGE_SECONDS: u64 = 60 * 60;

use latent_core::PackageDigest;

/// Untrusted association metadata, without any SBOM authenticity assertion.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SbomReference {
    pub subject: PackageDigest,
    pub media_type: String,
    pub digest: String,
}
