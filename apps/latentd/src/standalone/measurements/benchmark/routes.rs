use std::time::Instant;

use latent_core::{ContractId, FunctionId, ServiceId, TenantId};
use latent_routing::{InvocationTarget, RouteResolver};
use serde_json::json;

use super::{platform, MeasurementNode, MeasurementWriter, Result};

pub(super) fn sample(
    node: &MeasurementNode,
    writer: &mut MeasurementWriter,
    index: u32,
) -> Result<()> {
    let fixture = &node.fixtures.echo;
    let target = InvocationTarget {
        tenant: TenantId(fixture.tenant.clone()),
        service: ServiceId(fixture.service.clone()),
        contract: ContractId(fixture.contract.clone()),
        function: FunctionId("echo".to_owned()),
        route: None,
    };
    node.before_command(false)?;
    let started = Instant::now();
    let resolved = node
        .deployments
        .resolve(&target, Some("measurement-route-key"))
        .map_err(platform)?;
    let elapsed = started.elapsed().as_nanos();
    if resolved.target != target
        || resolved.release.0 != fixture.release_digest
        || resolved.route_generation != node.deployments.generation()
    {
        return Err("benchmark route receipt mismatch".into());
    }
    writer.write("benchmark-route",&json!({"sample":index.to_string(),"boundary":"directory-deployment-resolver.resolve",
        "elapsed_nanos":elapsed.to_string(),"tenant":target.tenant.0,"service":target.service.0,"contract":target.contract.0,
        "function":target.function.0,"release_digest":resolved.release.0,"revision_id":resolved.revision.0,
        "route_generation":resolved.route_generation.0.to_string()}))?;
    Ok(())
}
