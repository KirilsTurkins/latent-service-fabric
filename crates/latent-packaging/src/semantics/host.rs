use super::{compare::Comparison, incompatible, SemanticLimits};
use latent_core::{HostAbiProfile, PlatformError, PHASE3_HOST_ABI_CURRENT};
use std::collections::{BTreeMap, BTreeSet};
use wit_parser::{InterfaceId, Resolve};

pub(super) fn validate(
    resolve: &Resolve,
    imports: &BTreeMap<String, InterfaceId>,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    validate_for_profile(resolve, imports, limits, PHASE3_HOST_ABI_CURRENT)
}

pub(super) fn validate_for_profile(
    resolve: &Resolve,
    imports: &BTreeMap<String, InterfaceId>,
    limits: SemanticLimits,
    profile: HostAbiProfile,
) -> Result<(), PlatformError> {
    let mut trusted = Resolve::default();
    let mut loaded = BTreeSet::new();
    // One shared structural work allowance for non-callable type interfaces.
    // Self-comparison rejects resources, handles, futures and unknown shapes;
    // no provider binding or capability is created by these value definitions.
    let mut values = Comparison::new(resolve, resolve, limits);
    for (name, id) in imports {
        if profile.interface(name).is_none() {
            if !resolve.interfaces[*id].functions.is_empty() {
                return Err(incompatible("unsupported-host-import"));
            }
            values.interface(*id, *id)?;
        }
    }
    for specification in profile.interfaces() {
        let required = imports.contains_key(specification.interface)
            || (specification.interface == "latent:state/key-value@0.2.0"
                && imports.contains_key("latent:intents/staging@0.1.0"));
        if !required {
            continue;
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
        let Some(specification) = profile.interface(name) else {
            continue;
        };
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
            profile,
        )?;
    }
    Ok(())
}

#[cfg(test)]
mod tests;
