use latent_routing::RouteResolver;
use serde_json::json;

use super::observation::{Counts, Operation};
use super::resolve::{self, Input, Oracle, Outcome};
use super::{Clock, Node, Plan, Result, Writer};

struct Frame<'a> {
    node: &'a mut Node,
    counts: &'a mut Counts,
    input: &'a Input,
    expected: &'a Outcome,
    samples: u32,
}

#[derive(Default)]
struct Batch {
    attempted: u32,
    ok: u32,
    error: u32,
    validated: u32,
    command_failed: bool,
}

impl Batch {
    fn complete(&self, expected: u32) -> bool {
        !self.command_failed
            && self.attempted == expected
            && self.ok + self.error == expected
            && self.validated == expected
    }
}

/// Inlined into exactly one selected, retained frame. No fixture, oracle,
/// serialization, hashing or input construction belongs in this loop.
#[inline(always)]
#[allow(clippy::inline_always)] // Keep every measured allocation inside its selected frame.
fn batch(frame: &mut Frame<'_>, count: u32) -> Batch {
    let mut receipt = Batch::default();
    for _ in 0..count {
        if frame.counts.issued(frame.node, Operation::Resolve).is_err() {
            receipt.command_failed = true;
            break;
        }
        receipt.attempted += 1;
        let result = frame
            .node
            .deployments
            .resolve(&frame.input.target, Some(&frame.input.key));
        frame.counts.returned(Operation::Resolve, result.is_ok());
        if result.is_ok() {
            receipt.ok += 1;
        } else {
            receipt.error += 1;
        }
        receipt.validated += u32::from(&result == frame.expected);
        drop(result);
    }
    receipt
}

#[inline(never)]
fn measured_default_success_and_drop(frame: &mut Frame<'_>) -> Batch {
    let samples = frame.samples;
    let result = batch(frame, samples);
    std::hint::black_box(0_u8);
    result
}

#[inline(never)]
fn measured_named_success_and_drop(frame: &mut Frame<'_>) -> Batch {
    let samples = frame.samples;
    let result = batch(frame, samples);
    std::hint::black_box(1_u8);
    result
}

#[inline(never)]
fn measured_route_miss_and_drop(frame: &mut Frame<'_>) -> Batch {
    let samples = frame.samples;
    let result = batch(frame, samples);
    std::hint::black_box(2_u8);
    result
}

#[inline(never)]
fn measured_export_miss_and_drop(frame: &mut Frame<'_>) -> Batch {
    let samples = frame.samples;
    let result = batch(frame, samples);
    std::hint::black_box(3_u8);
    result
}

type Measured = fn(&mut Frame<'_>) -> Batch;

fn selected(case: &str) -> Result<(&'static str, Measured)> {
    Ok(match case {
        "default-success" => (
            "measured_default_success_and_drop",
            measured_default_success_and_drop,
        ),
        "named-success" => (
            "measured_named_success_and_drop",
            measured_named_success_and_drop,
        ),
        "route-miss" => ("measured_route_miss_and_drop", measured_route_miss_and_drop),
        "export-miss" => (
            "measured_export_miss_and_drop",
            measured_export_miss_and_drop,
        ),
        _ => return Err("unknown catalog allocation case".into()),
    })
}

pub(super) fn run(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    count: u32,
    clock: Clock,
) -> Result<()> {
    let case = plan
        .case
        .as_deref()
        .ok_or("catalog allocation case missing")?;
    let (symbol, measured) = selected(case)?;
    let input = resolve::input(&node.fixture, plan, count, case, 0);
    let oracle = Oracle::new(&node.fixture, plan, count, false)?;
    counts.issued(node, Operation::Resolve)?;
    let started = clock.elapsed();
    let expected = node.deployments.resolve(&input.target, Some(&input.key));
    let finished = clock.elapsed();
    counts.returned(Operation::Resolve, expected.is_ok());
    let preflight = resolve::outcome(&expected)?;
    let mut row = preflight.clone();
    row["kind"] = json!("allocation-preflight");
    row["case"] = json!(case);
    row["count"] = json!(count.to_string());
    row["index"] = json!("0");
    row["ordinal"] = json!(node.work.commands.to_string());
    row["started_nanos"] = json!(started.to_string());
    row["finished_nanos"] = json!(finished.to_string());
    writer.sample(&row)?;
    oracle.validate(&node.fixture, plan, &input, case, 1, &expected)?;
    drop((oracle, row));
    let mut frame = Frame {
        node,
        counts,
        input: &input,
        expected: &expected,
        samples: plan.allocation_samples(),
    };
    let warmup = batch(&mut frame, 16);
    let started = clock.elapsed();
    let invoked = warmup.complete(16);
    let receipt = if invoked {
        measured(&mut frame)
    } else {
        Batch::default()
    };
    let finished = clock.elapsed();
    writer.sample(&json!({"kind":"allocation-frame","case":case,"count":count.to_string(),
        "index":"0","key":input.key,"symbol":symbol,"preflight_calls":"1","preflight":preflight,
        "warmup_attempted":warmup.attempted.to_string(),"warmup_returned_ok":warmup.ok.to_string(),
        "warmup_returned_error":warmup.error.to_string(),"warmup_validated":warmup.validated.to_string(),
        "frame_invocations":u32::from(invoked).to_string(),"samples":plan.allocation_samples().to_string(),
        "attempted":receipt.attempted.to_string(),"returned_ok":receipt.ok.to_string(),
        "returned_error":receipt.error.to_string(),"validated":receipt.validated.to_string(),
        "contained_calls":receipt.attempted.to_string(),"full_result_equality":true,
        "started_nanos":started.to_string(),"finished_nanos":finished.to_string()}))?;
    if !invoked || !receipt.complete(plan.allocation_samples()) {
        return Err("catalog allocation result/population mismatch".into());
    }
    Ok(())
}
