use std::collections::BTreeMap;
use std::fs;

use latent_artifacts::package::{LayerRole, PackageKind};
use latent_packaging::{
    build_package, decode_package_source, read_package_directory, read_package_input,
    write_package_directory, PackageFile, PackageSource, PackagingLimits,
};

fn source() -> PackageSource {
    PackageSource {
        format_version: 1,
        kind: PackageKind::BrowserAssets,
        name: "browser".into(),
        version: "1.0.0".into(),
        entrypoint: "index.html".into(),
        annotations: BTreeMap::new(),
        layers: vec![
            PackageFile {
                path: "index.html".into(),
                source: "site/index.html".into(),
                role: LayerRole::Asset,
                media_type: "text/html".into(),
            },
            PackageFile {
                path: "app.js".into(),
                source: "site/app.js".into(),
                role: LayerRole::Asset,
                media_type: "text/javascript".into(),
            },
        ],
    }
}

fn input_tree() -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    fs::create_dir(root.path().join("site")).unwrap();
    fs::write(root.path().join("site/index.html"), b"html").unwrap();
    fs::write(root.path().join("site/app.js"), b"code").unwrap();
    root
}

#[test]
fn source_roots_and_input_order_do_not_change_package_identity() {
    let first = input_tree();
    let second = input_tree();
    let limits = PackagingLimits::default();
    let a = build_package(
        read_package_input(first.path(), &source(), limits).unwrap(),
        limits,
    )
    .unwrap();
    let mut reversed = source();
    reversed.layers.reverse();
    let b = build_package(
        read_package_input(second.path(), &reversed, limits).unwrap(),
        limits,
    )
    .unwrap();
    assert_eq!(a.manifest_bytes(), b.manifest_bytes());
    let output = first.path().join("built");
    write_package_directory(&a, &output).unwrap();
    let restored = read_package_directory(&output, limits).unwrap();
    assert_eq!(restored.layout().digest(), a.layout().digest());
    assert_eq!(restored.blob("index.html"), Some(b"html".as_slice()));
    assert!(restored.surface().is_none());
    assert_eq!(restored.build_receipt().unwrap().inputs.len(), 2);
}

#[test]
fn directory_inventory_tampering_and_existing_output_are_rejected() {
    let root = input_tree();
    let limits = PackagingLimits::default();
    let bundle = build_package(
        read_package_input(root.path(), &source(), limits).unwrap(),
        limits,
    )
    .unwrap();
    let output = root.path().join("built");
    write_package_directory(&bundle, &output).unwrap();
    assert!(write_package_directory(&bundle, &output).is_err());
    assert_eq!(
        fs::read(output.join("manifest.json")).unwrap(),
        bundle.manifest_bytes()
    );
    fs::write(output.join("extra.wasm"), b"unlisted component").unwrap();
    assert!(read_package_directory(&output, limits).is_err());
    fs::remove_file(output.join("extra.wasm")).unwrap();
    fs::write(output.join("layers/app.js"), b"evil").unwrap();
    assert!(read_package_directory(&output, limits).is_err());
    fs::write(output.join("layers/app.js"), b"code").unwrap();
    fs::rename(
        output.join("manifest.json"),
        output.join("manifest.pending"),
    )
    .unwrap();
    assert!(read_package_directory(&output, limits).is_err());
}

#[test]
fn bounded_input_reads_reject_nonfiles_unsafe_names_and_aggregate_overflow() {
    let root = input_tree();
    let mut limits = PackagingLimits::default();
    limits.package.max_layer_bytes = 4;
    limits.package.max_total_layer_bytes = 8;
    assert!(read_package_input(root.path(), &source(), limits).is_ok());
    limits.package.max_total_layer_bytes = 7;
    assert!(read_package_input(root.path(), &source(), limits).is_err());
    let limits = PackagingLimits::default();
    for path in [
        "../secret",
        "/secret",
        "site/../secret",
        "site\\index.html",
        "CON",
        "site/",
    ] {
        let mut recipe = source();
        recipe.layers[0].source = path.into();
        assert!(
            read_package_input(root.path(), &recipe, limits).is_err(),
            "{path}"
        );
    }
    let mut recipe = source();
    recipe.layers[0].source = "site".into();
    assert!(read_package_input(root.path(), &recipe, limits).is_err());
    let mut recipe = source();
    recipe.layers[1].path = "INDEX.html".into();
    assert!(read_package_input(root.path(), &recipe, limits).is_err());
}

#[test]
fn source_recipe_decoder_is_closed_and_bounded() {
    let limits = PackagingLimits::default();
    let bytes = serde_json::to_vec(&source()).unwrap();
    assert_eq!(
        decode_package_source(&bytes, limits).unwrap().layers.len(),
        2
    );
    let mut small = limits;
    small.package.max_document_bytes = bytes.len() - 1;
    assert!(decode_package_source(&bytes, small).is_err());
    let text = String::from_utf8(bytes).unwrap();
    for replacement in ["1.0", "1e0", "null", "true", "2"] {
        assert!(decode_package_source(
            text.replace(
                "\"formatVersion\":1",
                &format!("\"formatVersion\":{replacement}")
            )
            .as_bytes(),
            limits
        )
        .is_err());
    }
    assert!(
        decode_package_source(text.replacen('{', "{\"unknown\":1,", 1).as_bytes(), limits).is_err()
    );
    assert!(decode_package_source(
        text.replacen('{', "{\"formatVersion\":1,", 1).as_bytes(),
        limits
    )
    .is_err());
}

#[cfg(unix)]
#[test]
fn input_symlinks_at_leaf_and_directory_segments_never_escape() {
    use std::os::unix::fs::symlink;
    let root = input_tree();
    let outside = input_tree();
    fs::remove_file(root.path().join("site/index.html")).unwrap();
    symlink(
        outside.path().join("site/index.html"),
        root.path().join("site/index.html"),
    )
    .unwrap();
    assert!(read_package_input(root.path(), &source(), PackagingLimits::default()).is_err());
    fs::remove_file(root.path().join("site/index.html")).unwrap();
    fs::remove_file(root.path().join("site/app.js")).unwrap();
    fs::remove_dir(root.path().join("site")).unwrap();
    symlink(outside.path().join("site"), root.path().join("site")).unwrap();
    assert!(read_package_input(root.path(), &source(), PackagingLimits::default()).is_err());
}
