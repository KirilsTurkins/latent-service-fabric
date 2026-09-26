use super::{capacity, error, selected, BindingDefinition, CompiledCatalog, CompilerOwner};
use latent_core::{PlatformError, PlatformErrorCode, ServiceId, TenantId};
use latent_manifest::BindingMode;

type Node = (TenantId, ServiceId);

/// The generic dispatcher's destination tenant is an installed publication fact,
/// not the binding document's consumer tenant. Check the actual graph as well as
/// the conservative unconfigured direct-interface graph.
pub(super) fn configured_graph(
    catalog: &CompiledCatalog,
    definitions: &[BindingDefinition],
    owner: &CompilerOwner,
) -> Result<(), PlatformError> {
    let mut edges = Vec::new();
    for definition in definitions {
        let Ok(provider) = selected(definition, owner) else {
            // An absent or ambiguous installation cannot produce a usable plan.
            continue;
        };
        if provider.mode() != BindingMode::IsolatedLocal {
            continue;
        }
        let Some(target) = provider
            .local_deployment
            .as_ref()
            .and_then(|id| catalog.record_by_id(id))
        else {
            continue;
        };
        let (Some(consumer_tenant), Some(target_tenant)) = (
            definition.manifest.metadata.tenant.as_ref(),
            target.deployment.metadata.tenant.as_ref(),
        ) else {
            continue;
        };
        edges.push((
            (
                consumer_tenant.clone(),
                definition.manifest.consumer.service.clone(),
            ),
            (target_tenant.clone(), target.deployment.service.clone()),
        ));
    }
    check_edges(&edges, owner.limits.maximum_graph_depth)
}

fn check_edges(edges: &[(Node, Node)], limit: usize) -> Result<(), PlatformError> {
    fn walk<'a>(
        edges: &'a [(Node, Node)],
        node: &'a Node,
        path: &mut Vec<&'a Node>,
        limit: usize,
        work: &mut usize,
    ) -> Result<(), PlatformError> {
        if path.contains(&node) || path.len() >= limit {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "binding-cycle-or-depth",
            ));
        }
        path.push(node);
        for (source, target) in edges {
            *work = work.checked_add(1).ok_or_else(capacity)?;
            if *work > 131_072 {
                return Err(capacity());
            }
            if source == node {
                walk(edges, target, path, limit, work)?;
            }
        }
        path.pop();
        Ok(())
    }
    let mut work = 0;
    for (source, _) in edges {
        walk(edges, source, &mut Vec::new(), limit, &mut work)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{check_edges, Node};
    fn node(tenant: &str, service: &str) -> Node {
        (
            latent_core::TenantId(tenant.into()),
            latent_core::ServiceId(service.into()),
        )
    }
    #[test]
    fn installed_graph_distinguishes_tenants_and_rejects_cross_tenant_cycles() {
        let a = node("a", "service");
        let b = node("b", "service");
        let c = node("b", "leaf");
        assert!(check_edges(&[(a.clone(), b.clone()), (b.clone(), c)], 3).is_ok());
        assert!(check_edges(&[(a.clone(), b.clone()), (b, a.clone())], 8).is_err());
        assert!(check_edges(&[(a.clone(), a.clone())], 8).is_err());
        assert!(check_edges(&[(a, node("b", "leaf"))], 1).is_err());
    }
}
