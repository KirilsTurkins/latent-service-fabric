//! Projection from the existing immutable indexes, without a second resolver.
use super::{error, CompiledCatalog, RecordIndex};
use latent_core::{PlatformError, PlatformErrorCode};
use latent_routing::InvocationTarget;

impl CompiledCatalog {
    pub(in crate::deployments) fn inspection_members(
        &self,
        target: &InvocationTarget,
        maximum: usize,
    ) -> Result<Vec<(RecordIndex, bool)>, PlatformError> {
        let Some(route) = self.find_route(target) else {
            return Ok(Vec::new());
        };
        if route.revisions.len() > maximum {
            return Err(error(PlatformErrorCode::ResourceExhausted, "target-candidate-limit"));
        }
        let endpoint = self.find_endpoint(route, target);
        let mut members = Vec::with_capacity(route.revisions.len());
        for index in &self.route_revisions[route.revisions.clone()] {
            let exported = endpoint.is_some_and(|endpoint| {
                self.candidates[endpoint.candidates.clone()].binary_search_by(|candidate| {
                    self.record(candidate.record).revision.cmp(&self.record(*index).revision)
                }).is_ok()
            });
            members.push((*index, exported));
        }
        Ok(members)
    }
}
