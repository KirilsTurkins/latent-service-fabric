//! Restricted build attestations. Syntax and signed builder assertions are
//! distinct from observing a compiler locally or authorizing catalog admission.
pub(crate) mod codec;
pub(crate) mod evidence;
pub(crate) mod json;
mod limits;
mod model;
mod signer;
mod validate;

pub use codec::{inspect_provenance, UnverifiedProvenance};
pub use evidence::{ProvenanceEvidence, ProvenanceEvidenceRef};
pub use limits::ProvenanceLimits;
pub use model::{BuildMaterial, BuildObservation, BuildParameters, BuildSource};
pub use signer::LocalBuilderSigner;
pub(crate) use validate::{
    validate_digest, validate_observation, validate_repository, validate_revision,
};

use crate::SignatureResult;

pub const PROVENANCE_PAYLOAD_TYPE: &str = "application/vnd.in-toto+json";
pub const PROVENANCE_PREDICATE_TYPE: &str = "https://latent.dev/provenance/v1";
pub const PROVENANCE_BUILD_TYPE: &str = "https://latent.dev/build/echo-capsule/v1";
pub(crate) const STATEMENT_TYPE: &str = "https://in-toto.io/Statement/v1";

/// Decode unsigned observations from the maintained build driver. This does not
/// authenticate their origin or establish that the reported execution happened.
pub fn decode_build_observation(
    bytes: &[u8],
    limits: ProvenanceLimits,
) -> SignatureResult<BuildObservation> {
    limits.validate()?;
    let value = json::decode(bytes, limits.max_payload_bytes, limits.max_materials)?;
    validate_observation(&value, limits)?;
    Ok(value)
}
