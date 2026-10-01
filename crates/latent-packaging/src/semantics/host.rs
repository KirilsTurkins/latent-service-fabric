use super::{compare::Comparison, incompatible, SemanticLimits};
use latent_core::{HostInterfaceSpec, PlatformError, PHASE3_HOST_ABI_CURRENT, PHASE4_HOST_ABI_V1};
use std::collections::{BTreeMap, BTreeSet};
use wit_parser::{InterfaceId, Resolve};

pub(super) fn recognizes(name: &str) -> bool {
    specification(name).is_some()
}

// Recognition checks descriptive bytes only. The stateless runtime default,
// explicit transaction installation and current namespace authority are separate.
pub(super) fn specification(name: &str) -> Option<&'static HostInterfaceSpec> {
    PHASE3_HOST_ABI_CURRENT
        .interface(name)
        .or_else(|| PHASE4_HOST_ABI_V1.interface(name))
}

pub(super) fn validate(
    resolve: &Resolve,
    imports: &BTreeMap<String, InterfaceId>,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    let mut trusted = Resolve::default();
    let mut loaded = BTreeSet::new();
    for name in imports.keys() {
        let specification =
            specification(name).ok_or_else(|| incompatible("unsupported-host-import"))?;
        if name == "latent:intents/staging@0.1.0" {
            // Its borrowed transaction is the exact resource in state@0.2.0,
            // including when the source world imports only staging.
            let dependency = PHASE4_HOST_ABI_V1
                .interface("latent:state/key-value@0.2.0")
                .expect("immutable Phase 4 state dependency");
            if loaded.insert(dependency.wit) {
                trusted
                    .push_source(dependency.interface, dependency.wit)
                    .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
            }
        }
        // Semantic inspection recognizes the exact ABI without installing or
        // authorizing a provider. Runtime preparation checks actual availability.
        let source = specification.wit;
        // A capsule may import both HTTP package versions. Deduplicate exact
        // immutable sources, never the unversioned package name.
        if loaded.insert(source) {
            trusted
                .push_source(specification.interface, source)
                .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
        }
    }
    // One work allowance across every required host, including repeated type
    // visits. A caller cannot reset the comparison budget by adding interfaces.
    let mut comparison = Comparison::new(resolve, &trusted, limits);
    for (name, id) in imports {
        let specification =
            specification(name).ok_or_else(|| incompatible("unsupported-host-import"))?;
        let interface = trusted
            .interfaces
            .iter()
            .find_map(|(index, _)| {
                (trusted.id_of(index).as_deref() == Some(name.as_str())).then_some(index)
            })
            .ok_or_else(|| incompatible("pinned-host-interface-missing"))?;
        comparison.host_interface(
            *id,
            interface,
            specification.asynchronous,
            specification.resource_types(),
        )?;
    }
    Ok(())
}

#[cfg(test)]
mod tests;
