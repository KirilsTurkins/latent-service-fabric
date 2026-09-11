use std::collections::{BTreeMap, BTreeSet};
use std::ops::Range;
use std::sync::Arc;

use latent_core::{ContractId, FunctionId, PlatformError, PlatformErrorCode, ServiceId, TenantId};

use super::{
    charge, error, CompiledCatalog, DirectoryDeploymentRepositoryConfig, RecordIndex,
    RevisionRecord,
};

use super::super::observation::{count, Work};

type RouteKey = (String, String, String);
type EndpointKey = (ContractId, FunctionId);

pub(super) struct RouteRow {
    pub scope_record: RecordIndex,
    pub named: bool,
    pub revisions: Range<usize>,
    pub endpoints: Range<usize>,
}

pub(super) struct EndpointRow {
    pub contract: ContractId,
    pub function: FunctionId,
    pub candidates: Range<usize>,
    pub total_weight: u64,
}

pub(super) struct WeightedCandidate {
    pub cumulative_weight: u64,
    pub record: RecordIndex,
}

struct StagedRoute {
    scope_record: RecordIndex,
    named: bool,
    revisions: Vec<RecordIndex>,
    endpoints: BTreeMap<EndpointKey, Vec<RecordIndex>>,
}

#[derive(Default)]
pub(super) struct Builder {
    routes: BTreeMap<RouteKey, StagedRoute>,
    entries: usize,
}

pub(super) struct Packed {
    pub routes: Box<[RouteRow]>,
    pub route_revisions: Box<[RecordIndex]>,
    pub endpoints: Box<[EndpointRow]>,
    pub candidates: Box<[WeightedCandidate]>,
}

#[derive(Default)]
pub(super) struct IndexBudget {
    entries: usize,
}
impl IndexBudget {
    pub(super) fn charge_record(
        &mut self,
        record: &RevisionRecord,
        callable_count: usize,
        config: DirectoryDeploymentRepositoryConfig,
        remaining: &mut usize,
    ) -> Result<(), PlatformError> {
        for _ in 0..2 {
            // Keep default attributes/memberships before named attributes/memberships.
            for value in record.attributes.values() {
                charge(remaining, value.len())?;
            }
            self.entries = self
                .entries
                .checked_add(callable_count)
                .ok_or_else(index_limit)?;
            if self.entries > config.max_route_entries {
                return Err(index_limit());
            }
        }
        Ok(())
    }
}

impl Builder {
    pub(super) fn insert_checked(
        &mut self,
        position: RecordIndex,
        record: &RevisionRecord,
        callable: &BTreeSet<(String, String)>,
        work: &mut Work,
    ) {
        let deployment = &record.deployment;
        let tenant = deployment
            .metadata
            .tenant
            .as_ref()
            .expect("validated tenant");
        for (name, named) in [("default", false), (deployment.id.0.as_str(), true)] {
            let route = self
                .routes
                .entry((
                    tenant.0.clone(),
                    deployment.service.0.clone(),
                    name.to_owned(),
                ))
                .or_insert_with(|| {
                    if !named {
                        count!(work, scopes_staged, 1);
                    }
                    StagedRoute {
                        scope_record: position,
                        named,
                        revisions: Vec::new(),
                        endpoints: BTreeMap::new(),
                    }
                });
            if position.0 < route.scope_record.0 {
                route.scope_record = position;
            }
            route.revisions.push(position);
            for (contract, function) in callable {
                self.entries += 1; // Already checked by the ordered IndexBudget pass.
                route
                    .endpoints
                    .entry((ContractId(contract.clone()), FunctionId(function.clone())))
                    .or_default()
                    .push(position);
                count!(work, route_memberships_staged, 1);
            }
        }
    }

    pub(super) fn finish(self, records: &[Arc<RevisionRecord>]) -> Result<Packed, PlatformError> {
        let mut routes = Vec::with_capacity(self.routes.len());
        let mut route_revisions = Vec::new();
        let mut endpoints = Vec::new();
        let mut candidates = Vec::with_capacity(self.entries);
        for mut route in self.routes.into_values() {
            route
                .revisions
                .sort_unstable_by(|a, b| records[a.0].revision.cmp(&records[b.0].revision));
            let revision_start = route_revisions.len();
            route_revisions.extend(route.revisions);
            let endpoint_start = endpoints.len();
            for ((contract, function), mut members) in route.endpoints {
                members.sort_unstable_by(|a, b| records[a.0].revision.cmp(&records[b.0].revision));
                let start = candidates.len();
                let mut total_weight = 0_u64;
                for record in members {
                    total_weight = total_weight
                        .checked_add(u64::from(records[record.0].deployment.route_weight))
                        .ok_or_else(|| {
                            error(
                                PlatformErrorCode::ResourceExhausted,
                                "route-weight-overflow",
                            )
                        })?;
                    candidates.push(WeightedCandidate {
                        cumulative_weight: total_weight,
                        record,
                    });
                }
                endpoints.push(EndpointRow {
                    contract,
                    function,
                    candidates: start..candidates.len(),
                    total_weight,
                });
            }
            routes.push(RouteRow {
                scope_record: route.scope_record,
                named: route.named,
                revisions: revision_start..route_revisions.len(),
                endpoints: endpoint_start..endpoints.len(),
            });
        }
        Ok(Packed {
            routes: routes.into_boxed_slice(),
            route_revisions: route_revisions.into_boxed_slice(),
            endpoints: endpoints.into_boxed_slice(),
            candidates: candidates.into_boxed_slice(),
        })
    }
}

fn index_limit() -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, "route-index-limit")
}

#[derive(Clone, Copy)]
pub(in crate::deployments) struct RouteView<'a> {
    catalog: &'a CompiledCatalog,
    row: &'a RouteRow,
}

impl<'a> RouteView<'a> {
    pub(in crate::deployments) fn id(&self) -> &'a str {
        if self.row.named {
            &self.catalog.record(self.row.scope_record).deployment.id.0
        } else {
            "default"
        }
    }
    pub(in crate::deployments) fn tenant(&self) -> &'a TenantId {
        self.catalog
            .record(self.row.scope_record)
            .deployment
            .metadata
            .tenant
            .as_ref()
            .expect("validated tenant")
    }
    pub(in crate::deployments) fn service(&self) -> &'a ServiceId {
        &self
            .catalog
            .record(self.row.scope_record)
            .deployment
            .service
    }
    pub(in crate::deployments) fn revisions(
        &self,
    ) -> impl ExactSizeIterator<Item = &'a RevisionRecord> + 'a {
        let catalog = self.catalog;
        catalog.route_revisions[self.row.revisions.clone()]
            .iter()
            .map(move |index| catalog.record(*index))
    }
}

impl CompiledCatalog {
    pub(in crate::deployments) fn route_views(
        &self,
    ) -> impl ExactSizeIterator<Item = RouteView<'_>> {
        self.routes
            .iter()
            .map(|row| RouteView { catalog: self, row })
    }
    pub(in crate::deployments) fn tenant_routes(
        &self,
        tenant: &TenantId,
    ) -> impl ExactSizeIterator<Item = RouteView<'_>> {
        let start = self
            .routes
            .partition_point(|row| self.route_key(row).0 < tenant.0.as_str());
        let end = self
            .routes
            .partition_point(|row| self.route_key(row).0 <= tenant.0.as_str());
        self.routes[start..end]
            .iter()
            .map(|row| RouteView { catalog: self, row })
    }
    pub(super) fn route_key<'a>(&'a self, row: &RouteRow) -> (&'a str, &'a str, &'a str) {
        let manifest = &self.record(row.scope_record).deployment;
        (
            manifest
                .metadata
                .tenant
                .as_ref()
                .expect("validated tenant")
                .0
                .as_str(),
            manifest.service.0.as_str(),
            if row.named {
                manifest.id.0.as_str()
            } else {
                "default"
            },
        )
    }
}
