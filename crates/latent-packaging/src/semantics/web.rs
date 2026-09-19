use super::{arena, compare, incompatible, wasm, CheckedSurface, SemanticLimits, SurfaceCounts};
use crate::PackageBundle;
use latent_artifacts::{
    package::artifact_blob_digest,
    web::{
        inspect_web_layout, CheckedWebLayout, WebBackendProfile, WebRendererProfile,
        MAX_WEB_RENDERER_BYTES, WEB_CONTRACT, WEB_MANIFEST_PATH,
    },
};
use latent_core::PlatformError;
use wit_parser::{decoding::DecodedWasm, Resolve};

const WEB: &str = include_str!("../../../../wit/platform/web/package.wit");
const CONTEXT: &str = include_str!("../../../../wit/platform/context/package.wit");
const HTTP: &str = include_str!("../../../../wit/platform/http-v2/package.wit");
const WEB_HTTP: &str = include_str!("../../../../wit/platform/web-http/package.wit");

/// Validates all profile associations in an already byte-verified package. The
/// renderer is structurally checked, never compiled or executed. Format-only
/// browser/SSR packages remain inspectable without being eligible web releases.
pub fn inspect_web_bundle(
    package: &PackageBundle,
    limits: SemanticLimits,
) -> Result<CheckedWebLayout, PlatformError> {
    limits.validate()?;
    let manifest = package
        .blob(WEB_MANIFEST_PATH)
        .ok_or_else(|| super::invalid("web-manifest-missing"))?;
    let checked = inspect_web_layout(package.layout(), manifest)?;
    if let Some(renderer) = &checked.manifest().renderer {
        let bytes = package
            .blob(&renderer.layer)
            .ok_or_else(|| super::invalid("web-renderer-missing"))?;
        validate_web_renderer_with_backend(
            bytes,
            renderer.profile,
            renderer.backend_profile,
            limits,
        )?;
    }
    Ok(checked)
}

/// Exact public asynchronous web export and the closed context import subset.
/// A code digest is not catalog identity, current admission or execution authority.
pub fn validate_web_renderer(
    component: &[u8],
    profile: WebRendererProfile,
    limits: SemanticLimits,
) -> Result<CheckedSurface, PlatformError> {
    validate_web_renderer_with_backend(component, profile, WebBackendProfile::None, limits)
}

pub fn validate_web_renderer_with_backend(
    component: &[u8],
    profile: WebRendererProfile,
    backend: WebBackendProfile,
    mut limits: SemanticLimits,
) -> Result<CheckedSurface, PlatformError> {
    limits.validate()?;
    if !backend.is_none() && profile != WebRendererProfile::AngularSsrComponentV1 {
        return Err(incompatible("web-backend-profile-incompatible"));
    }
    let renderer_maximum = usize::try_from(MAX_WEB_RENDERER_BYTES)
        .map_err(|_| super::exhausted("component-byte-limit"))?;
    limits.max_component_bytes = limits.max_component_bytes.min(renderer_maximum);
    match profile {
        WebRendererProfile::WasmWebBufferedV1 => wasm::validate(component, limits)?,
        WebRendererProfile::AngularSsrComponentV1 => wasm::validate_renderer(component, limits)?,
    }
    let (source, world) = public_world(backend)?;
    let declared = compare::surface(&source, world, limits)?;
    let decoded = wit_parser::decoding::decode(component)
        .map_err(|_| incompatible("component-wit-decode-failed"))?;
    let DecodedWasm::Component(actual, actual_world) = decoded else {
        return Err(incompatible("wit-package-is-not-component"));
    };
    arena::resolved(&actual, limits)?;
    let compiled = compare::surface(&actual, actual_world, limits)?;
    let type_nodes = compare::worlds(&source, &declared, &actual, &compiled, limits)?;
    let source_packages = source_materials(backend);
    let counts = SurfaceCounts {
        source_packages: source_packages.len(),
        imports: declared.imports.len(),
        exports: 1,
        functions: source.interfaces[declared.exports[WEB_CONTRACT]]
            .functions
            .len(),
        type_nodes,
    };
    let summary_bytes = 1024
        + backend.world().len()
        + declared
            .imports
            .keys()
            .chain(declared.exports.keys())
            .map(|key| key.len() + 32)
            .sum::<usize>();
    if summary_bytes > limits.max_summary_bytes {
        return Err(super::exhausted("semantic-work-limit"));
    }
    Ok(CheckedSurface {
        component_digest: artifact_blob_digest(component),
        world: backend.world().into(),
        imports: declared
            .imports
            .into_keys()
            .map(String::into_boxed_str)
            .collect(),
        exports: declared
            .exports
            .into_keys()
            .map(String::into_boxed_str)
            .collect(),
        source_packages: source_packages.into_boxed_slice(),
        counts,
    })
}

fn source_materials(
    backend: WebBackendProfile,
) -> Vec<(Box<str>, latent_core::ArtifactBlobDigest)> {
    let mut sources = vec![("latent:context@0.1.0", CONTEXT), ("latent:web@0.1.0", WEB)];
    if !backend.is_none() {
        sources.extend([
            ("latent:http@0.2.0", HTTP),
            ("latent:web-http@0.1.0", WEB_HTTP),
        ]);
    }
    sources
        .into_iter()
        .map(|(name, source)| (name.into(), artifact_blob_digest(source.as_bytes())))
        .collect()
}

fn public_world(
    backend: WebBackendProfile,
) -> Result<(Resolve, wit_parser::WorldId), PlatformError> {
    let mut source = Resolve::default();
    source
        .push_source("context.wit", CONTEXT)
        .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
    let mut package = source
        .push_source("web.wit", WEB)
        .map_err(|_| incompatible("invalid-pinned-web-wit"))?;
    if !backend.is_none() {
        source
            .push_source("http.wit", HTTP)
            .map_err(|_| incompatible("invalid-pinned-host-wit"))?;
        package = source
            .push_source("web-http.wit", WEB_HTTP)
            .map_err(|_| incompatible("invalid-pinned-web-wit"))?;
    }
    let world = source
        .select_world(&[package], Some("application-service"))
        .map_err(|_| incompatible("invalid-pinned-web-world"))?;
    Ok((source, world))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backend_world_requests_only_the_exact_async_http_import() {
        let limits = SemanticLimits::default();
        let (source, world) = public_world(WebBackendProfile::ScopedHttpGetV1).unwrap();
        let declared = compare::surface(&source, world, limits).unwrap();
        assert_eq!(
            declared
                .imports
                .keys()
                .map(String::as_str)
                .collect::<Vec<_>>(),
            vec!["latent:context/context@0.1.0", "latent:http/client@0.2.0"]
        );
        assert_eq!(
            source.interfaces[declared.imports["latent:http/client@0.2.0"]].functions["send"].kind,
            wit_parser::FunctionKind::AsyncFreestanding
        );
        let (base, base_world) = public_world(WebBackendProfile::None).unwrap();
        let base_declared = compare::surface(&base, base_world, limits).unwrap();
        assert!(compare::worlds(&base, &base_declared, &source, &declared, limits).is_err());
        assert_eq!(
            source_materials(WebBackendProfile::ScopedHttpGetV1).len(),
            4
        );
        assert!(validate_web_renderer_with_backend(
            b"",
            WebRendererProfile::WasmWebBufferedV1,
            WebBackendProfile::ScopedHttpGetV1,
            limits
        )
        .is_err());
    }

    #[test]
    fn public_contract_is_async_and_a_profile_name_never_substitutes_for_a_component() {
        let (source, world) = public_world(WebBackendProfile::None).unwrap();
        let declared = compare::surface(&source, world, SemanticLimits::default()).unwrap();
        assert_eq!(declared.exports.len(), 1);
        assert_eq!(
            source.interfaces[declared.exports[WEB_CONTRACT]].functions["handle"].kind,
            wit_parser::FunctionKind::AsyncFreestanding
        );
        assert!(validate_web_renderer(
            b"\0asm\x0d\0\x01\0",
            WebRendererProfile::AngularSsrComponentV1,
            SemanticLimits::default()
        )
        .is_err());
        assert!(validate_web_renderer(
            b"\0asm\x0d\0\x01\0",
            WebRendererProfile::WasmWebBufferedV1,
            SemanticLimits::default()
        )
        .is_err());
    }

    #[test]
    fn sync_or_modified_public_interface_is_rejected_before_guest_execution() {
        let limits = SemanticLimits::default();
        let (source, world) = public_world(WebBackendProfile::None).unwrap();
        let declared = compare::surface(&source, world, limits).unwrap();
        for changed in [
            WEB.replace("async func", "func"),
            WEB.replace("status: u16", "status: u32"),
        ] {
            let mut other = Resolve::default();
            other.push_source("context.wit", CONTEXT).unwrap();
            let package = other.push_source("web.wit", &changed).unwrap();
            let world = other
                .select_world(&[package], Some("application-service"))
                .unwrap();
            let compiled = compare::surface(&other, world, limits).unwrap();
            assert!(compare::worlds(&source, &declared, &other, &compiled, limits).is_err());
        }
    }
}
