use std::time::Instant;

use latent_artifacts::content_digest;
use latent_control_store::deployment_revision_id;
use latent_core::{
    ContractId, FunctionId, PlatformError, PlatformErrorCode, ReleaseDigest, RevisionId, ServiceId,
    TenantId,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_routing::{InvocationTarget, ResolvedRevision, RouteResolver};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::super::super::{fixtures::Fixture, platform};
use super::observation::{self, Counts, Operation};
use super::{fixture, plan::CASES, Clock, Node, Plan, Result, Writer};

pub(super) type Outcome = std::result::Result<ResolvedRevision, PlatformError>;

pub(super) struct Input {
    pub index: u32,
    pub target: InvocationTarget,
    pub key: String,
}

pub(super) fn input(fixture: &Fixture, plan: &Plan, count: u32, case: &str, sample: u32) -> Input {
    let index = u32::try_from((u64::from(sample) * 7_919) % u64::from(count))
        .expect("index is below the u32 count");
    Input {
        index,
        target: InvocationTarget {
            tenant: TenantId(fixture.tenant.clone()),
            service: ServiceId(fixture::service(plan, index)),
            contract: ContractId(fixture.contract.clone()),
            function: FunctionId(
                if case == "export-miss" {
                    "missing-function"
                } else {
                    // Fixture's reusable wire target leaves this empty; callers
                    // normally choose a function through Fixture::request.
                    "echo"
                }
                .to_owned(),
            ),
            route: match case {
                "named-success" => Some(fixture::id(index)),
                "route-miss" => Some("missing-route".to_owned()),
                _ => None,
            },
        },
        key: format!("catalog-key-{sample:05}"),
    }
}

struct Entry {
    revision: RevisionId,
    release: ReleaseDigest,
}

/// Only identities and positional weights are retained, after the primary RSS sample.
pub(super) struct Oracle {
    entries: Box<[Entry]>,
    weighted: Box<[(usize, u64)]>,
    updated: bool,
}

impl Oracle {
    pub fn new(fixture: &Fixture, plan: &Plan, count: u32, updated: bool) -> Result<Self> {
        if count == 0 || count > 100_000 {
            return Err("catalog oracle count".into());
        }
        let capacity = usize::try_from(count).expect("bounded catalog count");
        let mut entries = Vec::with_capacity(capacity);
        for index in 0..count {
            let deployment = fixture::deployment(fixture, plan, index);
            entries.push(Entry {
                revision: deployment_revision_id(&deployment).map_err(platform)?,
                release: deployment.release,
            });
        }
        let mut order = (0..capacity).collect::<Vec<_>>();
        order
            .sort_unstable_by(|left, right| entries[*left].revision.cmp(&entries[*right].revision));
        let mut total = 0_u64;
        let weighted = order
            .into_iter()
            .map(|index| {
                total += if updated && index == 0 { 2 } else { 1 };
                (index, total)
            })
            .collect();
        Ok(Self {
            entries: entries.into_boxed_slice(),
            weighted,
            updated,
        })
    }

    fn selected(&self, plan: &Plan, input: &Input) -> usize {
        if plan.shape != "shared" || input.target.route.is_some() {
            return usize::try_from(input.index).expect("bounded fixture index");
        }
        let total = self.weighted.last().expect("nonempty oracle").1;
        let bucket = selection_hash(&input.target, &input.key) % total;
        self.weighted[self.weighted.partition_point(|(_, end)| *end <= bucket)].0
    }

    pub fn validate(
        &self,
        fixture: &Fixture,
        plan: &Plan,
        input: &Input,
        case: &str,
        generation: u64,
        result: &Outcome,
    ) -> Result<()> {
        if matches!(case, "route-miss" | "export-miss") {
            return validate_miss(case, result);
        }
        let resolved = result
            .as_ref()
            .map_err(|_| "catalog success returned error")?;
        let index = self.selected(plan, input);
        let expected = &self.entries[index];
        if resolved.target != input.target
            || resolved.revision != expected.revision
            || resolved.release != expected.release
            || resolved.route_generation.0 != generation
        {
            return Err("catalog resolved identity mismatch".into());
        }
        let mut deployment = fixture::deployment(
            fixture,
            plan,
            u32::try_from(index).expect("bounded fixture index"),
        );
        if self.updated && index == 0 {
            deployment.route_weight = 2;
        }
        let encoded = JsonManifestCodec::default()
            .encode_deployment(&deployment)
            .map_err(|_| "catalog expected deployment encoding")?;
        if resolved.attributes.len() != 2
            || resolved
                .attributes
                .get("lsf.deployment")
                .map(String::as_bytes)
                != Some(encoded.as_slice())
            || !resolved.attributes.contains_key("lsf.exports")
        {
            return Err("catalog resolved canonical deployment mismatch".into());
        }
        // Full export/schema content is independently checked from the retained
        // attributes digest by Python; no private compiler helper is consulted.
        Ok(())
    }
}

pub(in crate::standalone::measurements::comparison) fn validate_miss(
    case: &str,
    result: &Outcome,
) -> Result<()> {
    let (code, message) = if case == "route-miss" {
        (PlatformErrorCode::RouteUnavailable, "route-not-found")
    } else {
        (
            PlatformErrorCode::IncompatibleContract,
            "contract-or-function-not-exported",
        )
    };
    let Err(error) = result else {
        return Err("catalog miss returned success".into());
    };
    if error.code != code
        || error.message != message
        || error.retryable
        || error.details.len() != 1
        || error.details[0].kind != "deployment-catalog"
        || error.details[0].fields.len() != 1
        || error.details[0].fields.get("reason").map(String::as_str) != Some(message)
    {
        return Err("catalog miss error mismatch".into());
    }
    Ok(())
}

// The original public resolver's framed SHA-256 oracle, independent of either index.
pub(in crate::standalone::measurements::comparison) fn selection_hash(
    target: &InvocationTarget,
    key: &str,
) -> u64 {
    let mut frame = b"lsf-route-selection-v1\0".to_vec();
    for part in [
        target.tenant.0.as_str(),
        target.service.0.as_str(),
        target.route.as_deref().unwrap_or("default"),
        target.contract.0.as_str(),
        target.function.0.as_str(),
        key,
    ] {
        frame.extend_from_slice(
            &u64::try_from(part.len())
                .expect("bounded target part")
                .to_be_bytes(),
        );
        frame.extend_from_slice(part.as_bytes());
    }
    let digest = Sha256::digest(frame);
    u64::from_be_bytes(digest[..8].try_into().expect("SHA prefix"))
}

pub(in crate::standalone::measurements::comparison) fn outcome(result: &Outcome) -> Result<Value> {
    Ok(match result {
        Ok(value) => json!({"result":{"revision":value.revision.0,"release":value.release.0,
            "generation":value.route_generation.0.to_string(),
            "attributes_digest":content_digest(&serde_json::to_vec(&value.attributes)?).0}}),
        Err(error) => json!({"error":observation::error(error)}),
    })
}

pub(super) fn normal(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    count: u32,
    clock: Clock,
) -> Result<()> {
    let oracle = Oracle::new(&node.fixture, plan, count, false)?;
    let generation = u64::try_from(
        plan.scales()
            .iter()
            .position(|scale| *scale == count)
            .ok_or("catalog sample count outside scales")?,
    )? + 1;
    for case in CASES {
        for first in (0..plan.samples(case)).step_by(128) {
            let end = (first + 128).min(plan.samples(case));
            let inputs = (first..end)
                .map(|sample| input(&node.fixture, plan, count, case, sample))
                .collect::<Vec<_>>();
            let mut observations = Vec::with_capacity(inputs.len());
            let mut valid = true;
            let started = clock.elapsed();
            for value in &inputs {
                counts.issued(node, Operation::Resolve)?;
                let ordinal = node.work.commands;
                let begin = Instant::now();
                let result = node.deployments.resolve(&value.target, Some(&value.key));
                let elapsed = begin.elapsed().as_nanos();
                counts.returned(Operation::Resolve, result.is_ok());
                let mut row = outcome(&result)?;
                row["ordinal"] = json!(ordinal.to_string());
                row["index"] = json!(value.index.to_string());
                row["elapsed_nanos"] = json!(elapsed.to_string());
                observations.push(row);
                valid &= oracle
                    .validate(&node.fixture, plan, value, case, generation, &result)
                    .is_ok();
                drop(result);
            }
            let finished = clock.elapsed();
            writer.sample(
                &json!({"kind":"resolve-chunk","count":count.to_string(),"case":case,
                "first":first.to_string(),"started_nanos":started.to_string(),
                "finished_nanos":finished.to_string(),"observations":observations}),
            )?;
            if !valid {
                return Err("catalog resolve chunk failed semantic validation".into());
            }
        }
    }
    Ok(())
}
