//! Required by the actual observed Angular build gate; no synthetic Wasm input.
use latent_artifacts::web::{WebRendererProfile, WEB_MANIFEST_PATH};
use latent_packaging::*;

#[test]
#[ignore = "requires LSF_ANGULAR_PACKAGE_INPUTS from the maintained production builder"]
fn actual_angular_build_inputs_have_exact_renderer_assets_and_bound_inventory() {
    let root = std::path::PathBuf::from(
        std::env::var_os("LSF_ANGULAR_PACKAGE_INPUTS").expect("actual Angular package inputs"),
    );
    let limits = PackagingLimits::default();
    let source = decode_package_source(
        &std::fs::read(root.join("package-source.json")).unwrap(),
        limits,
    )
    .unwrap();
    let input = read_package_input(&root, &source, limits).unwrap();
    let inventory = decode_sbom_inventory(
        &std::fs::read(root.join("sbom-inputs.json")).unwrap(),
        limits.sbom,
    )
    .unwrap();
    let bundle = build_package_with_sbom(input, inventory, limits).unwrap();
    let web = inspect_web_bundle(&bundle, limits.semantics).unwrap();
    let renderer = web.manifest().renderer.as_ref().unwrap();
    assert_eq!(renderer.profile, WebRendererProfile::AngularSsrComponentV1);
    assert!(bundle.layout().config().component_digest.is_none());
    assert!(bundle.sbom().unwrap().entry_count() > 20);
    assert!(web
        .manifest()
        .assets
        .iter()
        .any(|asset| asset.path.starts_with("/client/") && asset.path.ends_with("/main.js")));
    assert!(web
        .manifest()
        .assets
        .iter()
        .all(|asset| asset.layer.starts_with("public/")));
    assert!(web
        .manifest()
        .assets
        .iter()
        .all(|asset| asset.layer != renderer.layer && asset.layer != WEB_MANIFEST_PATH));
    for asset in &web.manifest().assets {
        let bytes = bundle.blob(&asset.layer).unwrap();
        assert!(!bytes
            .windows(b"lsf-private-server-fixture-234".len())
            .any(|window| window == b"lsf-private-server-fixture-234"));
    }
}
