//! Generate package metadata from the same bounded WIT graph used by inspection.
use std::collections::BTreeMap;

use latent_artifacts::package::{artifact_blob_digest, WitLock, WitLockedPackage};
use latent_artifacts::{encode_contract_metadata, ContractMetadataLimits};
use latent_contracts::ContractDescriptor;
use latent_core::PlatformError;
use wit_parser::UnresolvedPackageGroup;

use super::SemanticLimits;
use super::{
    compare, exhausted, host, incompatible, invalid, lexical, limits, projection, sources,
};

/// Generated associations, not publisher, builder, admission or execution authority.
#[derive(Debug)]
pub struct CapsuleContractInputs {
    pub contracts: Vec<ContractDescriptor>,
    pub wit_lock: WitLock,
    pub imports: Vec<String>,
}

/// Derive descriptors and a pinned lock from authoritative UTF-8 WIT sources.
///
/// Each portable logical path contains exactly one versioned package. Multi-file
/// and nested packages must be consolidated explicitly; they are never guessed.
/// Resources are allowed in recognized host imports, not projected onto unsupported
/// public invocation values. Final packaging must still compare the compiled Wasm.
pub fn derive_capsule_contracts(
    sources: &BTreeMap<String, &[u8]>,
    world: &str,
    bounds: SemanticLimits,
) -> Result<CapsuleContractInputs, PlatformError> {
    bounds.validate()?;
    limits::name(world, bounds)?;
    if sources.is_empty() || sources.len() > bounds.max_wit_packages {
        return Err(exhausted("authoring-wit-package-limit"));
    }
    let mut bytes = 0;
    let mut tokens = 0;
    for (path, source) in sources {
        limits::name(path, bounds)?;
        limits::add(&mut bytes, source.len(), bounds.max_total_wit_bytes)?;
        if source.len() > bounds.max_wit_source_bytes {
            return Err(exhausted("wit-source-byte-limit"));
        }
        lexical::preflight(
            std::str::from_utf8(source).map_err(|_| invalid("wit-source-not-utf8"))?,
            &mut tokens,
            bounds,
        )?;
    }
    let mut packages = BTreeMap::new();
    for (path, source) in sources {
        let group = UnresolvedPackageGroup::parse(
            path,
            std::str::from_utf8(source).map_err(|_| invalid("wit-source-not-utf8"))?,
        )
        .map_err(|_| invalid("invalid-wit-source"))?;
        if !group.nested.is_empty() || group.main.name.version.is_none() {
            return Err(incompatible(
                "authoring-requires-one-pinned-package-per-source",
            ));
        }
        let id = group.main.name.to_string();
        let mut dependencies = Vec::new();
        for dependency in group.main.foreign_deps.keys() {
            if dependency.version.is_none() {
                return Err(incompatible("unpinned-wit-dependency"));
            }
            dependencies.push(dependency.to_string());
        }
        dependencies.sort();
        let package = WitLockedPackage {
            id: id.clone(),
            source_path: path.clone(),
            digest: artifact_blob_digest(source),
            dependencies,
        };
        if packages.insert(id, package).is_some() {
            return Err(incompatible(
                "authoring-requires-one-pinned-package-per-source",
            ));
        }
    }
    let mut lock = WitLock {
        format_version: 1,
        world: world.to_owned(),
        contracts_digest: artifact_blob_digest(b""),
        packages: packages.into_values().collect(),
    };
    // Reuse the admission packager's path, graph, parser and expansion limits.
    let (resolved, selected) = sources::resolve(&lock, sources, bounds)?;
    let surface = compare::surface(&resolved, selected, bounds)?;
    host::validate(&resolved, &surface.imports, bounds)?;
    let contracts = projection::generation::generate(&resolved, selected, bounds)?;
    let encoded = encode_contract_metadata(&contracts, ContractMetadataLimits::default())?;
    lock.contracts_digest = artifact_blob_digest(&encoded);
    Ok(CapsuleContractInputs {
        contracts,
        wit_lock: lock,
        imports: surface.imports.into_keys().collect(),
    })
}

#[cfg(test)]
pub(super) fn conformance_checks() {
    use latent_contracts::ValueType;
    let source = br"package authoring:typed@1.0.0;
        interface shared { record item { id: u64, label: string } }
        interface api {
            use shared.{item};
            record reply { values: list<item>, count: u64 }
            enum mode { fast, slow }
            call: func(id: u64, signed: s64, text: string, values: list<item>,
                mode: option<mode>) -> result<reply, string>;
            later: async func(bytes: list<u8>) -> result<u64, string>;
        }
        world service { export api; }";
    let sources = BTreeMap::from([("wit/service.wit".into(), &source[..])]);
    let generated = derive_capsule_contracts(
        &sources,
        "authoring:typed/service@1.0.0",
        SemanticLimits::default(),
    )
    .unwrap();
    assert!(generated.imports.is_empty());
    assert_eq!(generated.contracts.len(), 1);
    let contract = &generated.contracts[0];
    assert_eq!(contract.id.0, "authoring:typed/api@1.0.0");
    assert_eq!(contract.dependencies[0].0, "authoring:typed/shared@1.0.0");
    let functions = &contract.interfaces[0].functions;
    assert_eq!(functions[0].parameters[0].value_type, ValueType::U64);
    assert_eq!(functions[0].parameters[1].value_type, ValueType::S64);
    assert_eq!(functions[0].parameters[2].value_type, ValueType::String);
    assert_eq!(
        functions[0].parameters[3].value_type,
        ValueType::List(Box::new(ValueType::Record("item".into())))
    );
    assert!(functions[1].asynchronous);
    let encoded =
        encode_contract_metadata(&generated.contracts, ContractMetadataLimits::default()).unwrap();
    assert_eq!(
        generated.wit_lock.contracts_digest,
        artifact_blob_digest(&encoded)
    );
    assert_eq!(
        generated.wit_lock.packages[0].digest,
        artifact_blob_digest(source)
    );
    let repeated = derive_capsule_contracts(
        &sources,
        "authoring:typed/service@1.0.0",
        SemanticLimits::default(),
    )
    .unwrap();
    assert_eq!(generated.contracts, repeated.contracts);
    assert_eq!(generated.wit_lock, repeated.wit_lock);
    assert!(derive_capsule_contracts(
        &sources,
        "authoring:typed/missing@1.0.0",
        SemanticLimits::default()
    )
    .is_err());
    let mut duplicate = sources.clone();
    duplicate.insert("wit/other.wit".into(), source);
    assert!(derive_capsule_contracts(
        &duplicate,
        "authoring:typed/service@1.0.0",
        SemanticLimits::default()
    )
    .is_err());
    for source in [
        "package authoring:typed; interface api { call: func(); } world service { export api; }",
        "package authoring:typed@1.0.0; world service { export call: func(); }",
        "package authoring:typed@1.0.0; interface api { flags mask { one } record r { flags: mask } call: func(value: r); } world service { export api; }",
        "package authoring:typed@1.0.0; interface api { resource owned; call: func(value: borrow<owned>); } world service { export api; }",
        "package authoring:typed@1.0.0; interface api { call: func(value: future<string>); } world service { export api; }",
    ] {
        let sources = BTreeMap::from([("wit/service.wit".into(), source.as_bytes())]);
        assert!(derive_capsule_contracts(&sources, "authoring:typed/service@1.0.0", SemanticLimits::default()).is_err(), "{source}");
    }
}
