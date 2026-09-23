use base64::{engine::general_purpose::STANDARD, Engine};
use latent_policy::supply_chain::SupplyChainPolicy;
use latent_signing::{
    BuilderPolicy, ProvenanceLimits, PublisherPolicy, SignatureLimits, RUST_CAPSULE_BUILD_TYPE,
};
use serde_json::json;

use super::{inputs::Build, Result, BUILDER, PUBLISHER, TENANT};

pub(super) fn create(
    now: u64,
    publisher_key: &[u8; 32],
    builder_key: &[u8; 32],
    builds: &[Build],
) -> Result<(SupplyChainPolicy, Vec<u8>)> {
    let publisher = json!({"formatVersion":1,"scope":TENANT,"generation":1,"validFrom":now-60,"validUntil":now+3600,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"publisherId":PUBLISHER,"publicKey":STANDARD.encode(publisher_key),"validFrom":now-60,"validUntil":now+3600}]});
    let mut requirements = std::collections::BTreeMap::new();
    for build in builds {
        let source = &build.observation.source;
        requirements.insert(
            (
                source.repository.clone(),
                source.revision.clone(),
                source.snapshot_digest.clone(),
            ),
            json!({
            "builderId":BUILDER,"buildType":RUST_CAPSULE_BUILD_TYPE,
            "sourceRepository":source.repository,"sourceRevision":source.revision,
            "sourceSnapshotDigest":source.snapshot_digest,"requireReproducible":false}),
        );
    }
    let builder = json!({"formatVersion":1,"scope":TENANT,"generation":1,"validFrom":now-60,"validUntil":now+3600,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"builderId":BUILDER,"publicKey":STANDARD.encode(builder_key),"validFrom":now-60,"validUntil":now+3600}],
        "requirements":requirements.into_values().collect::<Vec<_>>()});
    let publisher_digest =
        PublisherPolicy::from_json(&serde_json::to_vec(&publisher)?, SignatureLimits::default())?
            .digest()
            .to_string();
    let builder_digest =
        BuilderPolicy::from_json(&serde_json::to_vec(&builder)?, ProvenanceLimits::default())?
            .digest()
            .to_string();
    let value = json!({"formatVersion":1,"generation":1,"scope":TENANT,"validFrom":now-60,"validUntil":now+3600,
        "tenants":[{"tenant":TENANT,"publishers":[PUBLISHER]}],"publisher":publisher,"builder":builder,
        "publisherRevocations":{"formatVersion":1,"scope":TENANT,"policyDigest":publisher_digest,"generation":1,"validFrom":now-60,"validUntil":now+3600,"revokedKeys":[],"revokedPublishers":[]},
        "builderRevocations":{"formatVersion":1,"scope":TENANT,"policyDigest":builder_digest,"generation":1,"validFrom":now-60,"validUntil":now+3600,"revokedKeys":[],"revokedBuilders":[]},
        "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}});
    let document = serde_json::to_vec(&value)?;
    let policy = SupplyChainPolicy::from_json(&document).map_err(|error| error.message)?;
    Ok((policy, document))
}
