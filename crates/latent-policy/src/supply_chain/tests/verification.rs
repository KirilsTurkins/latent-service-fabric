use super::*;
use latent_artifacts::ReleaseEvidenceUpload;
use latent_packaging::{inspect_bundle, BundleInput, PackageBundle, PackagingLimits};

fn inputs(fixture: &Fixture) -> (PackageBundle, ReleaseEvidenceUpload) {
    let upload = fixture.upload();
    (
        inspect_bundle(
            BundleInput {
                manifest: upload.manifest,
                configuration: upload.configuration,
                layers: upload.layers,
            },
            PackagingLimits::default(),
        )
        .unwrap(),
        ReleaseEvidenceUpload {
            signatures: upload.signatures,
            provenance: upload.provenance,
            sboms: upload.sboms,
        },
    )
}

#[test]
fn local_report_binds_joint_policy_without_grant_or_clock_history() {
    let fixture = Fixture::new();
    let (package, evidence) = inputs(&fixture);
    let pointer = package.layers()[0].bytes().as_ptr();
    let report = verify_package_once(
        &fixture.approved(),
        PackageVerificationRequest {
            tenant: &TenantId("tests".into()),
            package: &package,
            evidence: &evidence,
            unix_seconds: NOW,
        },
    )
    .unwrap();
    assert_eq!(
        report.package_digest(),
        package.layout().digest().to_string()
    );
    assert_eq!(report.checked_at_unix_seconds(), NOW);
    assert_eq!(pointer, package.layers()[0].bytes().as_ptr());
    let output = serde_json::to_value(&report).unwrap();
    assert_eq!(output["runtimeCompatibility"], "not-evaluated");
    assert_eq!(output["durablePolicyClockFloors"], false);
    assert_eq!(output["publisher"], "publisher-a");
    assert_eq!(output["builder"], "builder-a");
    assert!(output.get("grant").is_none());
    assert!(output.get("receipt").is_none());
}

#[test]
fn local_check_denies_wrong_tenant_expiry_missing_and_corrupt_evidence() {
    let fixture = Fixture::new();
    let (package, mut evidence) = inputs(&fixture);
    let policy = fixture.approved();
    let run = |evidence: &ReleaseEvidenceUpload, tenant: &str, now| {
        verify_package_once(
            &policy,
            PackageVerificationRequest {
                tenant: &TenantId(tenant.into()),
                package: &package,
                evidence,
                unix_seconds: now,
            },
        )
    };
    assert!(run(&evidence, "other", NOW).is_err());
    assert!(run(&evidence, "tests", 3000).is_err());
    evidence.provenance[0].payload[0] ^= 1;
    assert!(run(&evidence, "tests", NOW).is_err());
    evidence.provenance.clear();
    assert!(run(&evidence, "tests", NOW).is_err());
}

#[test]
fn local_check_uses_current_publisher_policy_and_sbom_requirements() {
    let fixture = Fixture::new();
    let (package, evidence) = inputs(&fixture);
    let mut denied_policy = fixture.policy.clone();
    denied_policy["publisherRevocations"]["revokedPublishers"] = serde_json::json!(["publisher-a"]);
    let revoked =
        SupplyChainPolicy::from_json(&serde_json::to_vec(&denied_policy).unwrap()).unwrap();
    let tenant = TenantId("tests".into());
    let request = || PackageVerificationRequest {
        tenant: &tenant,
        package: &package,
        evidence: &evidence,
        unix_seconds: NOW,
    };
    assert!(verify_package_once(&revoked, request()).is_err());
    let mut required = fixture.policy.clone();
    required["sbom"]["detached"] = serde_json::json!("required");
    let required = SupplyChainPolicy::from_json(&serde_json::to_vec(&required).unwrap()).unwrap();
    assert!(verify_package_once(&required, request()).is_err());
}
