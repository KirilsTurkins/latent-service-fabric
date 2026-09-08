//! Associate bounded replies with the one request that produced them.

use latent_wire::management::proto;

use crate::error::Failure;

use super::invalid_response;

pub(super) fn release(
    value: Option<&proto::ReleaseDescriptor>,
    tenant: &str,
    digest: Option<&str>,
    service: Option<&str>,
) -> Result<(), Failure> {
    if value.is_some_and(|value| {
        value.tenant.as_deref() != Some(tenant)
            || digest.is_some_and(|expected| value.digest != expected)
            || service.is_some_and(|expected| value.service != expected)
    }) {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) fn deployment(
    value: Option<&proto::Deployment>,
    tenant: &str,
    id: Option<&str>,
    service: Option<&str>,
) -> Result<(), Failure> {
    if value.is_some_and(|value| {
        value
            .metadata
            .as_ref()
            .and_then(|metadata| metadata.tenant.as_deref())
            != Some(tenant)
            || id.is_some_and(|expected| value.id != expected)
            || service.is_some_and(|expected| value.service != expected)
    }) {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) fn node(value: Option<&proto::NodeInventory>, id: &str) -> Result<(), Failure> {
    if value.is_some_and(|value| value.node.as_ref().is_none_or(|node| node.id != id)) {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) fn page_count(actual: usize, requested: u32) -> Result<(), Failure> {
    if requested != 0 && actual > usize::try_from(requested).map_err(|_| invalid_response())? {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) fn node_filters(
    value: &proto::NodeInventory,
    trust_class: Option<&str>,
    region: Option<&str>,
    zone: Option<&str>,
) -> Result<(), Failure> {
    let node = value.node.as_ref().ok_or_else(invalid_response)?;
    if trust_class.is_some_and(|expected| !node.trust_classes.iter().any(|value| value == expected))
        || region.is_some_and(|expected| node.region.as_deref() != Some(expected))
        || zone.is_some_and(|expected| node.zone.as_deref() != Some(expected))
    {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) fn route(
    value: Option<&proto::RouteSnapshot>,
    tenant: &str,
    generation: Option<u64>,
) -> Result<(), Failure> {
    if value.is_some_and(|value| {
        value.tenant.as_deref() != Some(tenant)
            || generation.is_some_and(|expected| value.generation != expected)
    }) {
        return Err(invalid_response());
    }
    Ok(())
}
