use super::{compare::Comparison, incompatible, SemanticLimits};
use latent_contracts::{HostInterfaceBinding, PHASE3_HOST_ABI_V1};
use latent_core::PlatformError;
use std::collections::BTreeMap;
use wit_parser::{InterfaceId, Resolve};

pub(super) fn recognizes(name: &str) -> bool {
    PHASE3_HOST_ABI_V1.interface(name).is_some()
}

pub(super) fn validate(
    resolve: &Resolve,
    imports: &BTreeMap<String, InterfaceId>,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    let mut trusted = Resolve::default();
    let mut loaded = BTreeMap::new();
    for (name, id) in imports {
        let specification = PHASE3_HOST_ABI_V1
            .interface(name)
            .ok_or_else(|| incompatible("unsupported-host-import"))?;
        if specification.binding != HostInterfaceBinding::BuiltIn {
            return Err(incompatible("host-provider-unavailable"));
        }
        let source = match specification.package {
            "latent:context" => include_str!("../../../../wit/platform/context/package.wit"),
            "latent:log" => include_str!("../../../../wit/platform/log/package.wit"),
            "latent:clock" => include_str!("../../../../wit/platform/clock/package.wit"),
            _ => return Err(incompatible("host-profile-package-unavailable")),
        };
        if !loaded.contains_key(specification.package) {
            let package_id = trusted
                .push_source(specification.package, source)
                .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
            loaded.insert(specification.package, package_id);
        }
        let interface = trusted
            .interfaces
            .iter()
            .find_map(|(index, _)| {
                (trusted.id_of(index).as_deref() == Some(name.as_str())).then_some(index)
            })
            .ok_or_else(|| incompatible("pinned-host-interface-missing"))?;
        Comparison::new(resolve, &trusted, limits).interface(*id, interface)?;
    }
    Ok(())
}
