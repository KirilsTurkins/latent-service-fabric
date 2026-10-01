//! Expose the verifier's bounded canonical public inputs; never establish trust.
use crate::error::Failure;
use latent_signing::{
    BuilderPolicy, ProvenanceLimits, PublisherPolicy, SignatureError, SignatureLimits,
};
use serde_json::{json, Value};

pub(super) fn canonicalize(publisher: &[u8], builder: &[u8]) -> Result<Value, Failure> {
    let publisher = PublisherPolicy::from_json(publisher, SignatureLimits::default())
        .map_err(|error| invalid("publisher-policy", error))?;
    let builder = BuilderPolicy::from_json(builder, ProvenanceLimits::default())
        .map_err(|error| invalid("builder-policy", error))?;
    Ok(json!({
        "schemaVersion": "latent.signing.canonical-policy.v1",
        "publisher": {"policyDigest": publisher.digest().as_str(),
            "canonicalJson": text(publisher.canonical_bytes())?},
        "builder": {"policyDigest": builder.digest().as_str(),
            "canonicalJson": text(builder.canonical_bytes())?},
        "limits": {"maximumInputBytesPerRole": 65_536, "maximumKeysPerRole": 64,
            "maximumBuilderRequirements": 64},
        "trustEstablished": false, "evidenceCreated": false,
        "executionAuthorized": false
    }))
}

fn text(bytes: &[u8]) -> Result<&str, Failure> {
    std::str::from_utf8(bytes).map_err(|_| {
        Failure::local(
            "canonical-policy-encoding",
            "The canonical policy could not be encoded.",
        )
    })
}

fn invalid(stage: &'static str, error: SignatureError) -> Failure {
    let mut failure = Failure::local(
        "canonical-policy-rejected",
        "Review the approved public inputs; duplicate keys and invalid encodings are rejected.",
    );
    failure.data = json!({"stage": stage, "reason": error.reason().code()});
    failure
}

#[cfg(test)]
mod tests;
