use super::{compare::Comparison, incompatible, SemanticLimits};
use latent_core::{PlatformError, PHASE3_HOST_ABI_V2};
use std::collections::BTreeMap;
use wit_parser::{InterfaceId, Resolve};

pub(super) fn recognizes(name: &str) -> bool {
    PHASE3_HOST_ABI_V2.interface(name).is_some()
}

pub(super) fn validate(
    resolve: &Resolve,
    imports: &BTreeMap<String, InterfaceId>,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    let mut trusted = Resolve::default();
    let mut loaded = BTreeMap::new();
    for name in imports.keys() {
        let specification = PHASE3_HOST_ABI_V2
            .interface(name)
            .ok_or_else(|| incompatible("unsupported-host-import"))?;
        // Semantic inspection recognizes the exact ABI without installing or
        // authorizing a provider. Runtime preparation checks actual availability.
        let source = specification.wit;
        if !loaded.contains_key(specification.package) {
            let package_id = trusted
                .push_source(specification.package, source)
                .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
            loaded.insert(specification.package, package_id);
        }
    }
    // One work allowance across every required host, including repeated type
    // visits. A caller cannot reset the comparison budget by adding interfaces.
    let mut comparison = Comparison::new(resolve, &trusted, limits);
    for (name, id) in imports {
        let specification = PHASE3_HOST_ABI_V2
            .interface(name)
            .ok_or_else(|| incompatible("unsupported-host-import"))?;
        let interface = trusted
            .interfaces
            .iter()
            .find_map(|(index, _)| {
                (trusted.id_of(index).as_deref() == Some(name.as_str())).then_some(index)
            })
            .ok_or_else(|| incompatible("pinned-host-interface-missing"))?;
        comparison.host_interface(*id, interface, specification.asynchronous)?;
    }
    Ok(())
}
