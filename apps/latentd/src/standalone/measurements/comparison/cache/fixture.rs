use latent_artifacts::content_digest;

use super::{cold, Fixture, Result};

pub(super) fn variants(base: &Fixture) -> Result<Vec<Fixture>> {
    let mut fixtures = cold::fixture::variants(base)?;
    fixtures.truncate(6);
    for fixture in &mut fixtures {
        let budget = &mut fixture.artifact.manifest.execution.resource_budget_ceiling;
        budget.cpu_fuel = 10_000_000_000;
        budget.memory_bytes = 16_777_216;
        budget.wall_time_limit_millis = Some(1000);
        budget.log_bytes = 16384;
        fixture.deployment.resources = budget.clone();
    }
    // Valid Component Model binary with no imports or exports. The retained
    // declared Echo metadata remains legal but must fail real surface linking.
    let invalid = &mut fixtures[5];
    invalid.artifact.component_bytes = b"\0asm\x0d\0\x01\0".to_vec();
    let digest = content_digest(&invalid.artifact.component_bytes);
    invalid.artifact.descriptor.release_digest = digest.clone();
    invalid.artifact.descriptor.size_bytes = 8;
    invalid.artifact.manifest.component_digest = digest.clone();
    invalid.deployment.release = digest.clone();
    invalid.release_digest = digest.0;
    Ok(fixtures)
}
