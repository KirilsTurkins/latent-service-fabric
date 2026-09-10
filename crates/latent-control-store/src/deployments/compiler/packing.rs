//! Rebuild dirty scopes; copy immutable compiled contents with checked positions.
use std::collections::{BTreeMap, BTreeSet};
use std::ops::Range;
use std::sync::Arc;

use latent_core::{PlatformError, ServiceId, TenantId};

use super::super::observation::{count, Work};
use super::index::{Builder, EndpointRow, Packed, RouteRow, WeightedCandidate};
use super::{reuse, CompiledCatalog, RecordIndex, RevisionRecord};

type Scope = (TenantId, ServiceId);
fn scope(record: &RevisionRecord) -> Scope {
    (
        record
            .deployment
            .metadata
            .tenant
            .clone()
            .expect("validated tenant"),
        record.deployment.service.clone(),
    )
}

struct Remap {
    positions: Box<[Option<RecordIndex>]>,
    dirty: BTreeSet<Scope>,
}
impl Remap {
    fn new(old: &CompiledCatalog, records: &[Arc<RevisionRecord>]) -> Self {
        let mut positions = vec![None; old.records.len()];
        let mut dirty = BTreeSet::new();
        let (mut left, mut right) = (0, 0);
        while left < old.records.len() || right < records.len() {
            let before = old.records.get(left);
            let after = records.get(right);
            match (before, after) {
                (Some(before), Some(after)) if before.deployment.id == after.deployment.id => {
                    positions[left] = Some(RecordIndex(right));
                    if !Arc::ptr_eq(before, after) {
                        dirty.insert(scope(before));
                        dirty.insert(scope(after));
                    }
                    left += 1;
                    right += 1;
                }
                (Some(before), Some(after)) if before.deployment.id < after.deployment.id => {
                    dirty.insert(scope(before));
                    left += 1;
                }
                (Some(before), None) => {
                    dirty.insert(scope(before));
                    left += 1;
                }
                (_, Some(after)) => {
                    dirty.insert(scope(after));
                    right += 1;
                }
                (None, None) => break,
            }
        }
        Self {
            positions: positions.into_boxed_slice(),
            dirty,
        }
    }
    fn map(&self, value: RecordIndex) -> Option<RecordIndex> {
        self.positions.get(value.0).copied().flatten()
    }
    fn valid(
        &self,
        previous: &CompiledCatalog,
        routes: Range<usize>,
        records: &[Arc<RevisionRecord>],
    ) -> bool {
        for route in &previous.routes[routes] {
            let Some(representative) = self.map(route.scope_record) else {
                return false;
            };
            let members = &previous.route_revisions[route.revisions.clone()];
            if members
                .iter()
                .filter_map(|member| self.map(*member))
                .map(|member| member.0)
                .min()
                != Some(representative.0)
            {
                return false;
            }
            for member in members.iter().copied().chain(
                previous.endpoints[route.endpoints.clone()]
                    .iter()
                    .flat_map(|endpoint| {
                        previous.candidates[endpoint.candidates.clone()]
                            .iter()
                            .map(|candidate| candidate.record)
                    }),
            ) {
                let Some(mapped) = self.map(member) else {
                    return false;
                };
                if !Arc::ptr_eq(&previous.records[member.0], &records[mapped.0]) {
                    return false;
                }
            }
        }
        true
    }
}

#[derive(Default)]
struct Appender {
    routes: Vec<RouteRow>,
    revisions: Vec<RecordIndex>,
    endpoints: Vec<EndpointRow>,
    candidates: Vec<WeightedCandidate>,
}
impl Appender {
    fn rebuilt(&mut self, packed: Packed) {
        let (revision_base, endpoint_base, candidate_base) = (
            self.revisions.len(),
            self.endpoints.len(),
            self.candidates.len(),
        );
        self.revisions.extend(packed.route_revisions);
        self.candidates.extend(packed.candidates);
        self.endpoints
            .extend(packed.endpoints.into_vec().into_iter().map(|mut endpoint| {
                endpoint.candidates.start += candidate_base;
                endpoint.candidates.end += candidate_base;
                endpoint
            }));
        self.routes
            .extend(packed.routes.into_vec().into_iter().map(|mut route| {
                route.revisions.start += revision_base;
                route.revisions.end += revision_base;
                route.endpoints.start += endpoint_base;
                route.endpoints.end += endpoint_base;
                route
            }));
    }
    fn reused(
        &mut self,
        previous: &CompiledCatalog,
        routes: Range<usize>,
        remap: &Remap,
        work: &mut Work,
    ) {
        // All mappings were preflighted before modifying any destination array.
        for route in &previous.routes[routes] {
            let revision_start = self.revisions.len();
            let endpoint_start = self.endpoints.len();
            self.revisions.extend(
                previous.route_revisions[route.revisions.clone()]
                    .iter()
                    .map(|member| remap.map(*member).expect("preflighted record")),
            );
            for endpoint in &previous.endpoints[route.endpoints.clone()] {
                let start = self.candidates.len();
                self.candidates.extend(
                    previous.candidates[endpoint.candidates.clone()]
                        .iter()
                        .map(|candidate| WeightedCandidate {
                            cumulative_weight: candidate.cumulative_weight,
                            record: remap.map(candidate.record).expect("preflighted candidate"),
                        }),
                );
                count!(
                    work,
                    route_memberships_remapped,
                    self.candidates.len() - start
                );
                self.endpoints.push(EndpointRow {
                    contract: endpoint.contract.clone(),
                    function: endpoint.function.clone(),
                    candidates: start..self.candidates.len(),
                    total_weight: endpoint.total_weight,
                });
            }
            self.routes.push(RouteRow {
                scope_record: remap.map(route.scope_record).expect("preflighted scope"),
                named: route.named,
                revisions: revision_start..self.revisions.len(),
                endpoints: endpoint_start..self.endpoints.len(),
            });
        }
        count!(work, scope_content_reuses, 1);
    }
    fn finish(self) -> Packed {
        Packed {
            routes: self.routes.into_boxed_slice(),
            route_revisions: self.revisions.into_boxed_slice(),
            endpoints: self.endpoints.into_boxed_slice(),
            candidates: self.candidates.into_boxed_slice(),
        }
    }
}

pub(super) fn assemble(
    records: &[Arc<RevisionRecord>],
    previous: Option<&CompiledCatalog>,
    work: &mut Work,
) -> Result<Packed, PlatformError> {
    let remap = previous.map(|previous| Remap::new(previous, records));
    assemble_using(records, previous, remap.as_ref(), work)
}

fn assemble_using(
    records: &[Arc<RevisionRecord>],
    previous: Option<&CompiledCatalog>,
    remap: Option<&Remap>,
    work: &mut Work,
) -> Result<Packed, PlatformError> {
    // One record walk groups positions. Never scan all records once per scope.
    let mut groups = BTreeMap::<Scope, Vec<RecordIndex>>::new();
    for (index, record) in records.iter().enumerate() {
        groups
            .entry(scope(record))
            .or_default()
            .push(RecordIndex(index));
    }
    let mut output = Appender::default();
    for (scope, positions) in groups {
        if let (Some(previous), Some(remap)) = (previous, remap) {
            let key = (scope.0 .0.as_str(), scope.1 .0.as_str());
            let start = previous.routes.partition_point(|route| {
                let row = previous.route_key(route);
                (row.0, row.1) < key
            });
            let end = previous.routes.partition_point(|route| {
                let row = previous.route_key(route);
                (row.0, row.1) <= key
            });
            if start < end
                && !remap.dirty.contains(&scope)
                && remap.valid(previous, start..end, records)
            {
                output.reused(previous, start..end, remap, work);
                continue;
            }
        }
        let mut builder = Builder::default();
        for position in positions {
            let record = &records[position.0];
            let surface = reuse::Surface::new(record)?;
            builder.insert_checked(position, record, &surface.callable(), work);
        }
        output.rebuilt(builder.finish(records)?);
    }
    Ok(output.finish())
}

#[cfg(test)]
pub(super) fn missing_mapping(
    previous: &CompiledCatalog,
    records: &[Arc<RevisionRecord>],
) -> Result<Packed, PlatformError> {
    let mut remap = Remap::new(previous, records);
    remap.positions[0] = None;
    assemble_using(records, Some(previous), Some(&remap), &mut Work::default())
}
