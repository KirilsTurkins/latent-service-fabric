//! A new current-clock signed fixture; historical constructors remain unchanged.
use super::*;
use std::time::{SystemTime, UNIX_EPOCH};

impl Fixture {
    pub fn freshly_signed() -> Self {
        let mut fixture = Self::new();
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let start = now.checked_sub(60).unwrap();
        let end = now.checked_add(3600).unwrap();
        for field in [
            None,
            Some("publisher"),
            Some("builder"),
            Some("publisherRevocations"),
            Some("builderRevocations"),
        ] {
            let document = if let Some(field) = field {
                &mut fixture.policy[field]
            } else {
                &mut fixture.policy
            };
            document["validFrom"] = start.into();
            document["validUntil"] = end.into();
        }
        for field in ["publisher", "builder"] {
            fixture.policy[field]["keys"][0]["validFrom"] = start.into();
            fixture.policy[field]["keys"][0]["validUntil"] = end.into();
        }
        fixture.policy["publisherRevocations"]["policyDigest"] = PublisherPolicy::from_json(
            &serde_json::to_vec(&fixture.policy["publisher"]).unwrap(),
            SignatureLimits::default(),
        )
        .unwrap()
        .digest()
        .to_string()
        .into();
        fixture.policy["builderRevocations"]["policyDigest"] = BuilderPolicy::from_json(
            &serde_json::to_vec(&fixture.policy["builder"]).unwrap(),
            ProvenanceLimits::default(),
        )
        .unwrap()
        .digest()
        .to_string()
        .into();
        let subject = PackageSigningSubject::from_package(
            fixture.bundle.manifest_bytes(),
            fixture.bundle.config_bytes(),
            PackageLimits::default(),
        )
        .unwrap();
        let validity = SignatureValidity {
            issued_at: now.checked_sub(1).unwrap(),
            expires_at: now.checked_add(1799).unwrap(),
        };
        fixture.signature = fixture
            .publisher_signer
            .sign_package(&subject, validity, SignatureLimits::default())
            .unwrap();
        let mut observed = observation(&subject);
        observed.started_at = now.checked_sub(3).unwrap();
        observed.finished_at = now.checked_sub(2).unwrap();
        fixture.provenance = fixture
            .builder_signer
            .sign_build(&subject, &observed, validity, ProvenanceLimits::default())
            .unwrap();
        fixture.clock.set(now);
        let _ = fixture.approved();
        fixture
    }
}
