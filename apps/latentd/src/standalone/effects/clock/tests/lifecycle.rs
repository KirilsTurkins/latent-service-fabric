#![allow(clippy::unwrap_used)]
use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_policy::supply_chain::{SupplyChainClock, SupplyChainPolicy};
use latent_signing::{BuilderPolicy, ProvenanceLimits, PublisherPolicy, SignatureLimits};
use serde_json::json;

const START_MILLIS: u64 = 1_100_000;

struct OriginalClock(Mutex<ClockSample>);
impl OriginalClock {
    fn advance(&self, millis: u64, elapsed: Duration) {
        let mut sample = self.0.lock().unwrap();
        *sample = ClockSample::new(millis, sample.monotonic() + elapsed);
    }
}
impl ActivationClock for OriginalClock {
    fn sample(&self) -> ClockSample {
        *self.0.lock().unwrap()
    }
    fn monotonic_now(&self) -> Instant {
        self.sample().monotonic()
    }
}
impl SupplyChainClock for OriginalClock {
    fn now(&self) -> Result<u64, PlatformError> {
        Ok(self.sample().unix_millis() / 1000)
    }
}

fn fixture() -> (
    tempfile::TempDir,
    Arc<OriginalClock>,
    Arc<SupplyChainAuthority>,
    Arc<ProtectedEffectClock>,
) {
    let root = tempfile::tempdir().unwrap();
    let clock = Arc::new(OriginalClock(Mutex::new(ClockSample::new(
        START_MILLIS,
        Instant::now(),
    ))));
    let authority =
        Arc::new(SupplyChainAuthority::open(root.path(), policy(), clock.clone(), 5).unwrap());
    let admitted = ProtectedEffectClock::admit(clock.clone(), authority.clone(), None).unwrap();
    (root, clock, authority, admitted)
}

fn policy() -> SupplyChainPolicy {
    let publisher_key = latent_signing::generate_signing_key().unwrap();
    let builder_key = latent_signing::generate_signing_key().unwrap();
    let publisher = json!({"formatVersion":1,"scope":"checkpoint-tests","generation":1,"validFrom":900,"validUntil":3000,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"publisherId":"publisher-a","publicKey":STANDARD.encode(publisher_key.public_key()),"validFrom":900,"validUntil":3000}]});
    let builder = json!({"formatVersion":1,"scope":"checkpoint-tests","generation":1,"validFrom":900,"validUntil":3000,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"builderId":"builder-a","publicKey":STANDARD.encode(builder_key.public_key()),"validFrom":900,"validUntil":3000}],
        "requirements":[{"builderId":"builder-a","buildType":latent_signing::PROVENANCE_BUILD_TYPE,"sourceRepository":"https://example.com/source","requireReproducible":false}]});
    let publisher_digest = PublisherPolicy::from_json(
        &serde_json::to_vec(&publisher).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap()
    .digest()
    .to_string();
    let builder_digest = BuilderPolicy::from_json(
        &serde_json::to_vec(&builder).unwrap(),
        ProvenanceLimits::default(),
    )
    .unwrap()
    .digest()
    .to_string();
    SupplyChainPolicy::from_json(&serde_json::to_vec(&json!({"formatVersion":1,"generation":1,"scope":"checkpoint-tests","validFrom":900,"validUntil":3000,
        "tenants":[{"tenant":"checkpoint-tests","publishers":["publisher-a"]}],"publisher":publisher,"builder":builder,
        "publisherRevocations":{"formatVersion":1,"scope":"checkpoint-tests","policyDigest":publisher_digest,"generation":1,"validFrom":900,"validUntil":3000,"revokedKeys":[],"revokedPublishers":[]},
        "builderRevocations":{"formatVersion":1,"scope":"checkpoint-tests","policyDigest":builder_digest,"generation":1,"validFrom":900,"validUntil":3000,"revokedKeys":[],"revokedBuilders":[]},
        "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}})).unwrap()).unwrap()
}

#[test]
fn actual_authority_retirement_rejects_a_previously_admitted_effect_clock() {
    let (_root, original, authority, admitted) = fixture();
    assert!(admitted.observe().continuity_proven);
    authority.retire();
    assert!(!admitted.observe().continuity_proven);
    original.advance(START_MILLIS + 1000, Duration::from_secs(1));
    assert!(!admitted.observe().continuity_proven);
}

#[test]
fn actual_clock_regression_cannot_be_repaired_by_a_later_forward_sample() {
    let (_root, original, _authority, admitted) = fixture();
    original.advance(START_MILLIS + 1000, Duration::from_secs(1));
    assert!(admitted.observe().continuity_proven);
    original.advance(START_MILLIS + 500, Duration::from_millis(500));
    assert!(!admitted.observe().continuity_proven);
    original.advance(START_MILLIS + 2000, Duration::from_millis(500));
    assert!(!admitted.observe().continuity_proven);
}

#[test]
fn actual_lease_renewal_cannot_revive_a_clock_that_already_lost_coverage() {
    let (_root, original, authority, admitted) = fixture();
    original.advance(START_MILLIS + 5000, Duration::from_secs(5));
    assert!(!admitted.observe().continuity_proven);
    authority.renew_clock_lease().unwrap();
    assert!(authority.covered_clock().is_ok());
    assert!(!admitted.observe().continuity_proven);
}
