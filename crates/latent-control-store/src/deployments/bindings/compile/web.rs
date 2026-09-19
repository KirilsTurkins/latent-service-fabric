use super::{
    definition, definition_digest, denied, grant, revision, selected, BindingDefinition,
    CompiledCatalog, CompilerOwner, PlatformError, ReleaseUseEligibility, RevisionRecord,
};
use latent_artifacts::web::{WebBackendProfile, WebRenderer, WEB_HTTP_CONTRACT};
use latent_capabilities::broker::{CapabilityBindingSpec, CompiledCapabilityPlan};
use latent_manifest::{CapabilityGrantSpec, RendererProfile};
use std::{sync::Arc, time::Instant};

pub(super) fn compile(
    catalog: &CompiledCatalog,
    record: &RevisionRecord,
    definitions: &[BindingDefinition],
    owner: &CompilerOwner,
    publication: &ReleaseUseEligibility,
    deadline: Instant,
) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
    let eligibility = publication.web_projection().ok_or_else(denied)?;
    let layout = eligibility.layout();
    let renderer = layout.manifest().renderer.as_ref().ok_or_else(denied)?;
    if record.deployment.service.0 != layout.name()
        || record.deployment.release.0 != renderer.digest
        || record.publication.as_ref() != Some(publication.publication())
    {
        return Err(denied());
    }
    let target = revision(record, catalog.generation);
    if !requires_http(renderer, &record.deployment.grants)? {
        return owner.broker.compile_invocation_plan(
            &target,
            Some(&record.deployment.id),
            &[],
            publication,
            &[],
            &[],
            &[],
            None,
            deadline,
        );
    }
    let definition = definition(record, definitions, WEB_HTTP_CONTRACT)?;
    let provider = selected(definition, owner)?;
    if provider.local_deployment.is_some()
        || provider.reference.capability() != WEB_HTTP_CONTRACT
        || provider.reference.profile() != "bounded-http-v1"
    {
        return Err(denied());
    }
    let definition_digest = definition_digest(definition)?;
    let (policies, restriction) = grant(record, definition, WEB_HTTP_CONTRACT)?;
    let operations = [String::from("send")];
    let binding = CapabilityBindingSpec {
        definition_digest: Some(&definition_digest),
        provider: &provider.reference,
        imported_operations: &operations,
        policy_ids: &policies,
        provider_binding_id: &definition.provider_binding_id,
        deployment_restriction_json: &restriction,
    };
    owner.broker.compile_invocation_plan(
        &target,
        Some(&record.deployment.id),
        &[binding],
        publication,
        &[],
        &[],
        &[],
        None,
        deadline,
    )
}

fn requires_http(
    renderer: &WebRenderer,
    grants: &[CapabilityGrantSpec],
) -> Result<bool, PlatformError> {
    match renderer.backend_profile {
        WebBackendProfile::None if grants.is_empty() => Ok(false),
        WebBackendProfile::ScopedHttpGetV1
            if renderer.profile == RendererProfile::AngularSsrComponentV1
                && grants.len() == 1
                && grants[0].capability.0 == WEB_HTTP_CONTRACT =>
        {
            Ok(true)
        }
        _ => Err(denied()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::{CapabilityId, PolicyId};

    fn renderer(backend_profile: WebBackendProfile) -> WebRenderer {
        WebRenderer {
            layer: "server/renderer.wasm".into(),
            digest: format!("sha256:{}", "1".repeat(64)),
            size: 1,
            profile: RendererProfile::AngularSsrComponentV1,
            profile_digest: format!("sha256:{}", "2".repeat(64)),
            assets_digest: format!("sha256:{}", "3".repeat(64)),
            backend_profile,
        }
    }

    fn http_grant() -> CapabilityGrantSpec {
        CapabilityGrantSpec::new(
            CapabilityId(WEB_HTTP_CONTRACT.into()),
            PolicyId("reference-http".into()),
        )
    }

    #[test]
    fn context_only_web_projection_cannot_acquire_provider_grants() {
        let renderer = renderer(WebBackendProfile::None);
        assert!(!requires_http(&renderer, &[]).unwrap());
        assert!(requires_http(&renderer, &[http_grant()]).is_err());
    }

    #[test]
    fn scoped_web_http_requires_one_exact_grant_without_ambient_imports() {
        let renderer = renderer(WebBackendProfile::ScopedHttpGetV1);
        assert!(requires_http(&renderer, &[http_grant()]).unwrap());
        assert!(requires_http(&renderer, &[]).is_err());
        assert!(requires_http(&renderer, &[http_grant(), http_grant()]).is_err());
        let mut unrelated = http_grant();
        unrelated.capability.0 = "latent:blob/blob@0.2.0".into();
        assert!(requires_http(&renderer, &[unrelated]).is_err());
    }
}
