use super::*;
use latent_packaging::{read_package_directory, PackagingLimits};
use latent_signing::{decode_web_build_observation, ProvenanceLimits, ANGULAR_BUILD_TYPE};

#[test]
#[ignore = "requires LSF_ANGULAR_BUILD_DIR from the actual maintained builder"]
fn actual_observed_angular_package_authenticates_publisher_builder_sbom_and_restart() {
    let root = std::path::PathBuf::from(
        std::env::var_os("LSF_ANGULAR_BUILD_DIR").expect("actual Angular build"),
    );
    let observed = decode_web_build_observation(
        &std::fs::read(root.join("observation.json")).unwrap(),
        ProvenanceLimits::default(),
    )
    .unwrap();
    assert_eq!(observed.build_type, ANGULAR_BUILD_TYPE);
    assert_eq!(observed.reproducibility, "not-checked");
    let now = observed.finished_at + 1;
    // Keys are created only after build children have exited. They are never
    // present in the source capture or the Node/Cargo/componentizer environment.
    let mut fixture = Fixture::new();
    fixture.enable_observed_angular_builder(now);
    let upload = || {
        let bundle =
            read_package_directory(&root.join("package"), PackagingLimits::default()).unwrap();
        assert!(bundle.sbom().is_some());
        fixture.sign_observed_web(bundle, &observed, observed.finished_at)
    };
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let admitted = owner
        .verify_web(&TenantId("tests".into()), upload())
        .unwrap();
    let binding = admitted.grant.binding().clone();
    assert_eq!(
        admitted
            .layout
            .manifest()
            .renderer
            .as_ref()
            .unwrap()
            .profile,
        latent_artifacts::web::WebRendererProfile::AngularSsrComponentV1
    );
    assert_eq!(admitted.layout.package(), &binding.package);
    for index in 0..3 {
        let mut changed = upload();
        match index {
            0 => changed.signatures.clear(),
            1 => changed.provenance.clear(),
            _ => {
                changed
                    .layers
                    .iter_mut()
                    .find(|(path, _)| path.starts_with("public/"))
                    .unwrap()
                    .1[0] ^= 1
            }
        }
        assert!(
            owner
                .verify_web(&TenantId("tests".into()), changed)
                .is_err(),
            "{index}"
        );
    }
    assert!(owner
        .verify_web(&TenantId("other".into()), upload())
        .is_err());
    drop(owner);
    fixture.clock.set(now + 5);
    let restarted = authority(&fixture, directory.path());
    let recovered = restarted.recover_web(&binding, upload()).unwrap();
    recovered.grant.check_current().unwrap();
    assert!(admitted.grant.check_current().is_err());
    // A web admission is publication permission; #226 still supplies the sealed
    // execution projection and the complete hardened renderer deployment gate.
}
