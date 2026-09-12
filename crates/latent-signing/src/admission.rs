use latent_artifacts::package::PackageSubject;
use latent_core::{
    ArtifactBlobDigest, PackageDigest, PlatformError, PlatformErrorCode, PublisherId,
};

use crate::{
    BuilderTrustStateId, BuilderVerifier, PackageSigningSubject, PublisherVerifier, TrustStateId,
    VerifiedBuildProvenance, VerifiedPackageSignature,
};

/// Current authenticated signature/provenance evidence for one exact capsule package.
///
/// Only [`verify_current_supply_chain_evidence`] constructs this value. It is an
/// admission input, not tenant authority, SBOM/content-policy approval, durable
/// catalog state, execution eligibility or a serializable trust token. A catalog
/// admission owner must additionally bind authenticated tenant scope, configured
/// SBOM/content policy and its own atomic publication state at commit time.
#[derive(Debug)]
pub struct VerifiedSupplyChainEvidence {
    subject: PackageSubject,
    component_digest: ArtifactBlobDigest,
    publisher: PublisherId,
    publisher_key_fingerprint: ArtifactBlobDigest,
    builder_id: Box<str>,
    builder_key_fingerprint: ArtifactBlobDigest,
    signature_evidence_digest: PackageDigest,
    signature_payload_digest: ArtifactBlobDigest,
    provenance_evidence_digest: PackageDigest,
    provenance_payload_digest: ArtifactBlobDigest,
    publisher_trust_state: TrustStateId,
    builder_trust_state: BuilderTrustStateId,
    verified_at: u64,
    valid_until: u64,
}

impl VerifiedSupplyChainEvidence {
    #[must_use]
    pub fn subject(&self) -> &PackageSubject {
        &self.subject
    }

    #[must_use]
    pub fn component_digest(&self) -> &ArtifactBlobDigest {
        &self.component_digest
    }

    #[must_use]
    pub fn publisher(&self) -> &PublisherId {
        &self.publisher
    }

    #[must_use]
    pub fn publisher_key_fingerprint(&self) -> &ArtifactBlobDigest {
        &self.publisher_key_fingerprint
    }

    #[must_use]
    pub fn builder_id(&self) -> &str {
        &self.builder_id
    }

    #[must_use]
    pub fn builder_key_fingerprint(&self) -> &ArtifactBlobDigest {
        &self.builder_key_fingerprint
    }

    #[must_use]
    pub fn signature_evidence_digest(&self) -> &PackageDigest {
        &self.signature_evidence_digest
    }

    #[must_use]
    pub fn signature_payload_digest(&self) -> &ArtifactBlobDigest {
        &self.signature_payload_digest
    }

    #[must_use]
    pub fn provenance_evidence_digest(&self) -> &PackageDigest {
        &self.provenance_evidence_digest
    }

    #[must_use]
    pub fn provenance_payload_digest(&self) -> &ArtifactBlobDigest {
        &self.provenance_payload_digest
    }

    #[must_use]
    pub fn publisher_trust_state(&self) -> &TrustStateId {
        &self.publisher_trust_state
    }

    #[must_use]
    pub fn builder_trust_state(&self) -> &BuilderTrustStateId {
        &self.builder_trust_state
    }

    #[must_use]
    pub const fn verified_at(&self) -> u64 {
        self.verified_at
    }

    #[must_use]
    pub const fn valid_until(&self) -> u64 {
        self.valid_until
    }
}

/// Rechecks current publisher and builder trust and binds both authenticated
/// proofs to the same exact executable package/component identity.
///
/// This function performs no network access and owns no cache or background
/// resource. Both verifiers are checked before and after identity binding so a
/// trust-state change observed during the operation fails closed. The returned
/// evidence still must be rechecked against current verifier states by the
/// catalog owner at its atomic publication point.
pub fn verify_current_supply_chain_evidence(
    expected: &PackageSigningSubject,
    publisher_verifier: &PublisherVerifier,
    signature: &VerifiedPackageSignature,
    builder_verifier: &BuilderVerifier,
    provenance: &VerifiedBuildProvenance,
    now: u64,
) -> Result<VerifiedSupplyChainEvidence, PlatformError> {
    publisher_verifier
        .check_current(signature, now)
        .map_err(PlatformError::from)?;
    builder_verifier
        .check_current(provenance, now)
        .map_err(PlatformError::from)?;

    let publisher_state = publisher_verifier.state_id().map_err(PlatformError::from)?;
    let builder_state = builder_verifier.state_id().map_err(PlatformError::from)?;

    let evidence = bind_current_evidence(
        expected,
        PublisherEvidenceView {
            subject: signature.subject(),
            publisher: signature.publisher(),
            key_fingerprint: signature.key_fingerprint(),
            evidence_digest: signature.evidence_digest(),
            payload_digest: signature.payload_digest(),
            state: signature.state_id(),
            verified_at: signature.verified_at(),
            valid_until: signature.valid_until(),
        },
        BuilderEvidenceView {
            subject: provenance.subject(),
            component_digest: provenance.component_digest(),
            builder_id: provenance.builder_id(),
            key_fingerprint: provenance.key_fingerprint(),
            evidence_digest: provenance.evidence_digest(),
            payload_digest: provenance.payload_digest(),
            state: provenance.state_id(),
            verified_at: provenance.verified_at(),
            valid_until: provenance.valid_until(),
        },
        &publisher_state,
        &builder_state,
        now,
    )?;

    // A replacement between the first currentness check and completed binding is
    // not allowed to leak a stale positive result from this helper.
    publisher_verifier
        .check_current(signature, now)
        .map_err(PlatformError::from)?;
    builder_verifier
        .check_current(provenance, now)
        .map_err(PlatformError::from)?;
    if publisher_verifier
        .state_id()
        .map_err(PlatformError::from)?
        != publisher_state
        || builder_verifier.state_id().map_err(PlatformError::from)? != builder_state
    {
        return Err(failure(
            PlatformErrorCode::StateConflict,
            "supply-chain-trust-changed-during-admission",
        ));
    }

    Ok(evidence)
}

struct PublisherEvidenceView<'a> {
    subject: &'a PackageSubject,
    publisher: &'a PublisherId,
    key_fingerprint: &'a ArtifactBlobDigest,
    evidence_digest: &'a PackageDigest,
    payload_digest: &'a ArtifactBlobDigest,
    state: &'a TrustStateId,
    verified_at: u64,
    valid_until: u64,
}

struct BuilderEvidenceView<'a> {
    subject: &'a PackageSubject,
    component_digest: &'a ArtifactBlobDigest,
    builder_id: &'a str,
    key_fingerprint: &'a ArtifactBlobDigest,
    evidence_digest: &'a PackageDigest,
    payload_digest: &'a ArtifactBlobDigest,
    state: &'a BuilderTrustStateId,
    verified_at: u64,
    valid_until: u64,
}

fn bind_current_evidence(
    expected: &PackageSigningSubject,
    publisher: PublisherEvidenceView<'_>,
    builder: BuilderEvidenceView<'_>,
    current_publisher_state: &TrustStateId,
    current_builder_state: &BuilderTrustStateId,
    now: u64,
) -> Result<VerifiedSupplyChainEvidence, PlatformError> {
    let component_digest = expected.component_digest().ok_or_else(|| {
        failure(
            PlatformErrorCode::InvalidArgument,
            "supply-chain-admission-requires-capsule-component",
        )
    })?;
    if publisher.subject != expected.subject()
        || builder.subject != expected.subject()
        || publisher.subject != builder.subject
    {
        return Err(failure(
            PlatformErrorCode::InvalidArgument,
            "supply-chain-package-subject-mismatch",
        ));
    }
    if builder.component_digest != component_digest {
        return Err(failure(
            PlatformErrorCode::InvalidArgument,
            "supply-chain-component-subject-mismatch",
        ));
    }
    if publisher.state != current_publisher_state || builder.state != current_builder_state {
        return Err(failure(
            PlatformErrorCode::StateConflict,
            "supply-chain-trust-state-mismatch",
        ));
    }

    let verified_at = publisher.verified_at.max(builder.verified_at);
    let valid_until = publisher.valid_until.min(builder.valid_until);
    if now < verified_at || now >= valid_until {
        return Err(failure(
            PlatformErrorCode::StateConflict,
            "supply-chain-evidence-not-current",
        ));
    }

    Ok(VerifiedSupplyChainEvidence {
        subject: expected.subject().clone(),
        component_digest: component_digest.clone(),
        publisher: PublisherId(fresh_string(&publisher.publisher.0)),
        publisher_key_fingerprint: publisher.key_fingerprint.clone(),
        builder_id: Box::<str>::from(builder.builder_id),
        builder_key_fingerprint: builder.key_fingerprint.clone(),
        signature_evidence_digest: publisher.evidence_digest.clone(),
        signature_payload_digest: publisher.payload_digest.clone(),
        provenance_evidence_digest: builder.evidence_digest.clone(),
        provenance_payload_digest: builder.payload_digest.clone(),
        publisher_trust_state: current_publisher_state.clone(),
        builder_trust_state: current_builder_state.clone(),
        verified_at,
        valid_until,
    })
}

fn fresh_string(value: &str) -> String {
    Box::<str>::from(value).into_string()
}

fn failure(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use latent_artifacts::package::{PackageSubject, OCI_MANIFEST_MEDIA_TYPE};
    use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformErrorCode, PublisherId};

    use crate::{BuilderTrustStateId, PackageSigningSubject, TrustStateId};

    use super::{
        bind_current_evidence, BuilderEvidenceView, PublisherEvidenceView,
    };

    fn blob(byte: char) -> ArtifactBlobDigest {
        format!("sha256:{}", byte.to_string().repeat(64))
            .parse()
            .unwrap()
    }

    fn package(byte: char) -> PackageDigest {
        format!("sha256:{}", byte.to_string().repeat(64))
            .parse()
            .unwrap()
    }

    fn publisher_state(byte: char) -> TrustStateId {
        crate::policy::state::test_state_id(blob(byte), blob('f'), 7, 11)
    }

    fn builder_state(byte: char) -> BuilderTrustStateId {
        crate::builder_policy::state::test_state_id(blob(byte), blob('e'), 5, 9)
    }

    fn subject() -> PackageSubject {
        PackageSubject {
            media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
            digest: package('a'),
            size: 123,
        }
    }

    fn expected() -> PackageSigningSubject {
        crate::subject::test_subject(subject(), Some(blob('b')))
    }

    #[test]
    fn exact_current_publisher_and_builder_evidence_is_bound() {
        let subject = subject();
        let publisher_state = publisher_state('c');
        let builder_state = builder_state('d');
        let publisher = PublisherId("publisher:test".to_owned());
        let evidence = bind_current_evidence(
            &expected(),
            PublisherEvidenceView {
                subject: &subject,
                publisher: &publisher,
                key_fingerprint: &blob('1'),
                evidence_digest: &package('2'),
                payload_digest: &blob('3'),
                state: &publisher_state,
                verified_at: 90,
                valid_until: 200,
            },
            BuilderEvidenceView {
                subject: &subject,
                component_digest: &blob('b'),
                builder_id: "builder:test",
                key_fingerprint: &blob('4'),
                evidence_digest: &package('5'),
                payload_digest: &blob('6'),
                state: &builder_state,
                verified_at: 100,
                valid_until: 180,
            },
            &publisher_state,
            &builder_state,
            120,
        )
        .unwrap();

        assert_eq!(evidence.subject(), &subject);
        assert_eq!(evidence.component_digest(), &blob('b'));
        assert_eq!(evidence.publisher().0, "publisher:test");
        assert_eq!(evidence.builder_id(), "builder:test");
        assert_eq!(evidence.verified_at(), 100);
        assert_eq!(evidence.valid_until(), 180);
    }

    #[test]
    fn package_component_and_trust_mismatches_fail_closed() {
        let expected = expected();
        let subject = subject();
        let publisher_state = publisher_state('c');
        let builder_state = builder_state('d');
        let publisher = PublisherId("publisher:test".to_owned());

        let wrong_subject = PackageSubject {
            digest: package('9'),
            ..subject.clone()
        };
        let error = bind_current_evidence(
            &expected,
            PublisherEvidenceView {
                subject: &wrong_subject,
                publisher: &publisher,
                key_fingerprint: &blob('1'),
                evidence_digest: &package('2'),
                payload_digest: &blob('3'),
                state: &publisher_state,
                verified_at: 90,
                valid_until: 200,
            },
            BuilderEvidenceView {
                subject: &subject,
                component_digest: &blob('b'),
                builder_id: "builder:test",
                key_fingerprint: &blob('4'),
                evidence_digest: &package('5'),
                payload_digest: &blob('6'),
                state: &builder_state,
                verified_at: 100,
                valid_until: 180,
            },
            &publisher_state,
            &builder_state,
            120,
        )
        .unwrap_err();
        assert_eq!(error.message, "supply-chain-package-subject-mismatch");

        let error = bind_current_evidence(
            &expected,
            PublisherEvidenceView {
                subject: &subject,
                publisher: &publisher,
                key_fingerprint: &blob('1'),
                evidence_digest: &package('2'),
                payload_digest: &blob('3'),
                state: &publisher_state,
                verified_at: 90,
                valid_until: 200,
            },
            BuilderEvidenceView {
                subject: &subject,
                component_digest: &blob('8'),
                builder_id: "builder:test",
                key_fingerprint: &blob('4'),
                evidence_digest: &package('5'),
                payload_digest: &blob('6'),
                state: &builder_state,
                verified_at: 100,
                valid_until: 180,
            },
            &publisher_state,
            &builder_state,
            120,
        )
        .unwrap_err();
        assert_eq!(error.message, "supply-chain-component-subject-mismatch");

        let other_publisher_state = publisher_state('7');
        let error = bind_current_evidence(
            &expected,
            PublisherEvidenceView {
                subject: &subject,
                publisher: &publisher,
                key_fingerprint: &blob('1'),
                evidence_digest: &package('2'),
                payload_digest: &blob('3'),
                state: &publisher_state,
                verified_at: 90,
                valid_until: 200,
            },
            BuilderEvidenceView {
                subject: &subject,
                component_digest: &blob('b'),
                builder_id: "builder:test",
                key_fingerprint: &blob('4'),
                evidence_digest: &package('5'),
                payload_digest: &blob('6'),
                state: &builder_state,
                verified_at: 100,
                valid_until: 180,
            },
            &other_publisher_state,
            &builder_state,
            120,
        )
        .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::StateConflict);
        assert_eq!(error.message, "supply-chain-trust-state-mismatch");
    }

    #[test]
    fn combined_validity_window_is_fail_closed() {
        let subject = subject();
        let publisher_state = publisher_state('c');
        let builder_state = builder_state('d');
        let publisher = PublisherId("publisher:test".to_owned());
        let error = bind_current_evidence(
            &expected(),
            PublisherEvidenceView {
                subject: &subject,
                publisher: &publisher,
                key_fingerprint: &blob('1'),
                evidence_digest: &package('2'),
                payload_digest: &blob('3'),
                state: &publisher_state,
                verified_at: 100,
                valid_until: 130,
            },
            BuilderEvidenceView {
                subject: &subject,
                component_digest: &blob('b'),
                builder_id: "builder:test",
                key_fingerprint: &blob('4'),
                evidence_digest: &package('5'),
                payload_digest: &blob('6'),
                state: &builder_state,
                verified_at: 110,
                valid_until: 125,
            },
            &publisher_state,
            &builder_state,
            125,
        )
        .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::StateConflict);
        assert_eq!(error.message, "supply-chain-evidence-not-current");
    }
}
