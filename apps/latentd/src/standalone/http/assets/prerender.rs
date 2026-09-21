use super::Request;
use crate::standalone::http::{head::Head, Shared};
use latent_artifacts::{web::WebRenderMode, LifecycleScope, PublicationRef};
use latent_control_store::http_routes::AcceptedHttpRoute;
use latent_core::PlatformErrorCode;
use latent_routing::RevisionPolicySource;

pub(in crate::standalone::http) fn select(
    head: &Head,
    shared: &Shared,
    accepted: &AcceptedHttpRoute,
    raw: &[u8],
) -> Result<Option<Request>, u16> {
    let Some(publication) = &accepted.revision().publication else {
        return Ok(None);
    };
    let tenant = &accepted.revision().target.tenant;
    let reference = PublicationRef {
        id: publication.clone(),
        scope: LifecycleScope::Tenant(tenant.clone()),
    };
    let store = shared.handle.0.assets.get().ok_or(503u16)?;
    let selection = match store.repository.select_web_publication(&reference) {
        Ok(selection) => selection,
        Err(error) if error.code == PlatformErrorCode::NotFound => return Ok(None),
        Err(error) => return Err(super::status(&error)),
    };
    let layout = selection.layout();
    if layout
        .manifest()
        .renderer
        .as_ref()
        .is_none_or(|renderer| renderer.digest != accepted.revision().release.0)
    {
        return Err(502);
    }
    let route = layout
        .manifest()
        .routes
        .iter()
        .find(|route| route.path == head.collector.target().path())
        .ok_or(404u16)?;
    if route.mode == WebRenderMode::Server {
        return Ok(None);
    }
    accepted
        .catalog()
        .admission_policy(accepted.revision())
        .map_err(|error| super::status(&error))?;
    if head.content_length != 0 {
        return Err(400);
    }
    let path = route.asset.as_ref().ok_or(502u16)?;
    Request::parse_routed(raw, tenant, reference, path.clone()).map(Some)
}
