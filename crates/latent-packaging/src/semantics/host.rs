use super::{compare::Comparison, incompatible, SemanticLimits};
use latent_core::{HostInterfaceSpec, PlatformError, PHASE3_HOST_ABI_CURRENT, PHASE4_HOST_ABI_V1};
use std::collections::{BTreeMap, BTreeSet};
use wit_parser::{InterfaceId, Resolve, Type, TypeDefKind, TypeId};

const STREAMING_HTTP: &str = "latent:http/streaming@0.3.0";
const UPLOAD_WINDOW: &str = "latent:http/upload-window@0.5.0";

pub(super) fn recognizes(name: &str) -> bool {
    specification(name).is_some()
}

// Recognition checks descriptive bytes only. The stateless runtime default,
// explicit transaction installation and current namespace authority are separate.
pub(super) fn specification(name: &str) -> Option<&'static HostInterfaceSpec> {
    PHASE3_HOST_ABI_CURRENT
        .interface(name)
        .or_else(|| PHASE4_HOST_ABI_V1.interface(name))
        // Descriptive exact-WIT recognition only. CURRENT and actual provider
        // installation remain unchanged; the native host profile is explicit.
        .or_else(|| latent_core::PHASE3_HOST_ABI_V6.interface(name))
        .or_else(|| latent_core::PHASE3_HOST_ABI_V7.interface(name))
        .or_else(|| latent_core::PHASE3_HOST_ABI_V8.interface(name))
}

/// Classify only the exact phase dependency after the caller validates its
/// complete declared source graph. This predicate supplies no provider authority.
pub(super) fn phase_type_owner(resolve: &Resolve, imports: &BTreeMap<String, InterfaceId>) -> bool {
    imports.contains_key("latent:http/phase-timing@0.4.0")
        && imports
            .get("latent:http/streaming@0.3.0")
            .is_some_and(|id| resolve.interfaces[*id].functions.is_empty())
}

fn resource_target(resolve: &Resolve, mut id: TypeId) -> Option<TypeId> {
    // Alias depth is already bounded by semantic validation. Keep this local
    // identity walk independently finite as well.
    for _ in 0..64 {
        match &resolve.types[id].kind {
            TypeDefKind::Type(Type::Id(next)) => id = *next,
            TypeDefKind::Resource => return Some(id),
            _ => return None,
        }
    }
    None
}

/// This helper can only continue an operational original streaming import. It
/// owns no resource of its own and creates no additional provider authority.
pub(super) fn upload_window_alias(
    resolve: &Resolve,
    imports: &BTreeMap<String, InterfaceId>,
) -> bool {
    let (Some(original), Some(helper)) = (imports.get(STREAMING_HTTP), imports.get(UPLOAD_WINDOW))
    else {
        return false;
    };
    let original = &resolve.interfaces[*original];
    let helper = &resolve.interfaces[*helper];
    if original.functions.is_empty() {
        return false;
    }
    match (original.types.get("upload"), helper.types.get("upload")) {
        (Some(a), Some(b)) => {
            let original = resource_target(resolve, *a);
            original.is_some() && original == resource_target(resolve, *b)
        }
        _ => false,
    }
}

pub(super) fn validate(
    resolve: &Resolve,
    imports: &BTreeMap<String, InterfaceId>,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    if imports.contains_key(UPLOAD_WINDOW) && !upload_window_alias(resolve, imports) {
        return Err(incompatible(
            "upload-window-requires-original-streaming-owner",
        ));
    }
    let mut trusted = Resolve::default();
    let mut loaded = BTreeSet::new();
    // One shared structural work allowance for non-callable type interfaces.
    // Self-comparison rejects resources, handles, futures and unknown shapes;
    // no provider binding or capability is created by these value definitions.
    let mut values = Comparison::new(resolve, resolve, limits);
    for (name, id) in imports {
        let Some(specification) = specification(name) else {
            if !resolve.interfaces[*id].functions.is_empty() {
                return Err(incompatible("unsupported-host-import"));
            }
            values.interface(*id, *id)?;
            continue;
        };
        if name == "latent:http/phase-timing@0.4.0" || name == UPLOAD_WINDOW {
            let dependency = PHASE3_HOST_ABI_CURRENT
                .interface("latent:http/streaming@0.3.0")
                .expect("immutable phase timing resource dependency");
            if loaded.insert(dependency.wit) {
                trusted
                    .push_source(dependency.interface, dependency.wit)
                    .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
            }
        }
        if name == "latent:runtime-native/threads@0.1.0" {
            let dependency = PHASE3_HOST_ABI_CURRENT
                .interface("latent:runtime/activation@0.1.0")
                .expect("immutable native runtime type dependency");
            if loaded.insert(dependency.wit) {
                trusted
                    .push_source(dependency.interface, dependency.wit)
                    .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
            }
        }
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
        let Some(specification) = specification(name) else {
            continue;
        };
        let interface = trusted
            .interfaces
            .iter()
            .find_map(|(index, _)| {
                (trusted.id_of(index).as_deref() == Some(name.as_str())).then_some(index)
            })
            .ok_or_else(|| incompatible("pinned-host-interface-missing"))?;
        // A phase-only world still imports its original nominal resource
        // interface. Component emission may prune the unused legacy response;
        // every retained type is pinned and no legacy operation is supplied.
        // Validate it in this same comparison budget; no provider is installed.
        if name == "latent:http/streaming@0.3.0" && phase_type_owner(resolve, imports) {
            comparison.host_type_owner(
                *id,
                interface,
                specification.resource_types(),
                &["response"],
            )?;
        } else {
            comparison.host_interface(
                *id,
                interface,
                specification.asynchronous,
                specification.resource_types(),
            )?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests;
