use super::{compare::Comparison, incompatible, SemanticLimits};
use latent_core::PlatformError;
use std::collections::BTreeMap;
use wit_parser::{InterfaceId, Resolve};

pub(super) const IMPORTS: [&str; 4] = [
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
    "latent:clock/monotonic@0.1.0",
    "latent:clock/wall@0.1.0",
];

pub(super) fn validate(
    resolve: &Resolve,
    imports: &BTreeMap<String, InterfaceId>,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    let mut trusted = Resolve::default();
    let mut loaded = BTreeMap::new();
    for (name, id) in imports {
        if !IMPORTS.contains(&name.as_str()) {
            return Err(incompatible("unsupported-host-import"));
        }
        let (package, source) = if name.starts_with("latent:context/") {
            (
                "latent:context",
                include_str!("../../../../wit/platform/context/package.wit"),
            )
        } else if name.starts_with("latent:log/") {
            (
                "latent:log",
                include_str!("../../../../wit/platform/log/package.wit"),
            )
        } else {
            (
                "latent:clock",
                include_str!("../../../../wit/platform/clock/package.wit"),
            )
        };
        if !loaded.contains_key(package) {
            let package_id = trusted
                .push_source(package, source)
                .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
            loaded.insert(package, package_id);
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
