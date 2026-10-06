//! Use the maintained semantic projection, including actual component types.
use super::{CONTRACT, WORLD};
use latent_artifacts::{decode_contract_metadata, ContractDescriptor, ContractMetadataLimits};
use latent_manifest::{CapsuleManifest, ManifestValidationProfile, TransactionBinding};
use latent_packaging::{derive_capsule_contracts, validate_capsule_with_profile, SemanticLimits};
use std::{collections::BTreeMap, fs, path::Path};

pub(super) fn contracts(
    root: &Path,
    component: &[u8],
    manifest: &CapsuleManifest,
    profile: ManifestValidationProfile,
) -> Vec<ContractDescriptor> {
    let sources: BTreeMap<String, &[u8]> = [
        (
            "wit/world.wit".into(),
            include_bytes!(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../examples/rust-capsules/transactional-aggregate/world.wit"
            ))
            .as_slice(),
        ),
        (
            "wit/deps/state/package.wit".into(),
            include_bytes!(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../wit/platform/state/package.wit"
            ))
            .as_slice(),
        ),
        (
            "wit/deps/intents/package.wit".into(),
            include_bytes!(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../wit/platform/intents/package.wit"
            ))
            .as_slice(),
        ),
    ]
    .into();
    for (path, source) in &sources {
        assert_eq!(
            fs::read(root.join("project").join(path)).unwrap(),
            *source,
            "compiled project must retain the maintained authoritative WIT"
        );
    }
    let bounds = SemanticLimits::default();
    let inputs = derive_capsule_contracts(WORLD, &sources, bounds).unwrap();
    let contracts =
        decode_contract_metadata(inputs.contracts(), ContractMetadataLimits::default()).unwrap();
    let checked = validate_capsule_with_profile(
        component,
        manifest,
        &contracts,
        inputs.wit_lock(),
        &sources,
        bounds,
        profile,
    )
    .unwrap();
    assert_eq!(checked.counts().exports, 1);
    assert_eq!(checked.counts().functions, 3);
    assert_eq!(contracts.len(), 1);
    assert_eq!(contracts[0].id.0, CONTRACT);
    assert!(contracts[0]
        .interfaces
        .iter()
        .flat_map(|interface| &interface.functions)
        .all(|function| function.asynchronous));
    contracts
}

pub(super) fn declaration(root: &Path, report: &serde_json::Value) -> TransactionBinding {
    let companion = fs::read(root.join("project/transaction-binding.json")).unwrap();
    assert_eq!(
        report["companionDigest"],
        latent_artifacts::content_digest(&companion).0
    );
    let schema = fs::read(root.join("project/state-schema.json")).unwrap();
    assert_eq!(
        schema,
        include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../examples/rust-capsules/transactional-aggregate/state-schema.json"
        ))
        .as_slice()
    );
    let declaration = TransactionBinding::decode(&companion).unwrap();
    assert_eq!(
        declaration.state_schema,
        latent_artifacts::content_digest(&schema).0
    );
    declaration
}
