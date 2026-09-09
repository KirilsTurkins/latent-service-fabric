//! Explicit codec-only measurements over owned values and a type-only component.

mod fixtures;
mod frames;
mod input;
mod output;
mod preflight;
mod timing;

use std::hint::black_box;
use std::time::{Duration, Instant};

use serde_json::json;
use wasmtime::component::Val;

use crate::preparation_observer::sample_thread_cpu;
use crate::values::ValueCodecLimits;

use fixtures::Fixture;

type ProbeResult<T> = Result<T, Box<dyn std::error::Error>>;

/// Called once per measured decode batch; warmup and preflight bypass this
/// attribution frame. Every contained codec result drops before it returns.
#[inline(never)]
fn measured_decode_and_drop(
    fixture: &Fixture,
    limits: ValueCodecLimits,
    count: usize,
) -> frames::Batch {
    let result = frames::decode_loop(black_box(fixture), black_box(limits), black_box(count));
    black_box(&result);
    result
}

/// The unchanged encoder borrows a common legacy-produced fixture. This frame
/// contains only the measured loop, its O(1) checks and actual result drops.
#[inline(never)]
fn measured_encode_and_drop(
    fixture: &Fixture,
    values: &[Val],
    limits: ValueCodecLimits,
    count: usize,
) -> frames::Batch {
    let result = frames::encode_loop(
        black_box(fixture),
        black_box(values),
        black_box(limits),
        black_box(count),
    );
    black_box(&result);
    result
}

#[test]
#[ignore = "explicit finite paired Linux codec measurement only"]
fn codec_collector() {
    collect().expect("codec collector");
}

fn collect() -> ProbeResult<()> {
    let origin = Instant::now();
    let input = input::Input::load()?;
    let fixture = Fixture::new(&input.plan.family)?;
    let limits = ValueCodecLimits::default();
    input
        .plan
        .validate_work(fixture.input.len(), fixture.expected.len())?;
    input::write_new(&input.output.join("input.json"), &fixture.input)?;
    input::write_new(
        &input.output.join("expected-output.json"),
        &fixture.expected,
    )?;
    let input_ref = input::file_ref("input.json", &fixture.input);
    let expected_ref = input::file_ref("expected-output.json", &fixture.expected);
    let (encoding_values, preflight) = preflight::verify(&fixture, limits, origin)?;
    let identity = sample_thread_cpu()
        .ok_or("codec ready task unavailable")?
        .identity;
    output::emit(&output::event(
        &input,
        identity,
        origin.elapsed().as_nanos(),
        false,
    ))?;
    std::thread::sleep(Duration::from_millis(100));

    let decode = timing::direction(
        "decode",
        &fixture,
        &encoding_values,
        limits,
        &input.plan,
        origin,
        identity,
    )?;
    let encode = timing::direction(
        "encode",
        &fixture,
        &encoding_values,
        limits,
        &input.plan,
        origin,
        identity,
    )?;
    // Wire counts are JSON strings; comparing them to integers changes the check.
    #[allow(clippy::cmp_owned)]
    let passed = [&decode, &encode].iter().all(|row| {
        row["failure"].is_null()
            && row["measured_successes"] == input.plan.measured_iterations.to_string()
            && row["warmup_successes"] == input.plan.warmup_iterations.to_string()
    });
    drop(encoding_values);
    drop(fixture);
    let outcome = if passed { "passed" } else { "failed" };
    let raw = json!({
        "schema": "latent.optimization.codec-arm.v1", "plan": input.plan, "identity": input.identity,
        "process_id": std::process::id(), "thread_identity": identity,
        "plan_sha256": input.plan_sha256, "identity_sha256": input.identity_sha256,
        "input": input_ref, "expected_output": expected_ref,
        "type_fixture": {"sha256": input::sha256(fixtures::TYPE_FIXTURE), "bytes": fixtures::TYPE_FIXTURE.len().to_string()},
        "limits": output::limits(limits), "preflight": preflight, "directions": [decode, encode],
        "types_dropped": true, "guest_stores": "0", "invokes": "0",
        "elapsed_nanos": origin.elapsed().as_nanos().to_string(), "outcome": outcome,
    });
    let bytes = serde_json::to_vec(&raw)?;
    input::write_new(&input.output.join("codec.json"), &bytes)?;
    let mut complete = output::event(&input, identity, origin.elapsed().as_nanos(), true);
    complete["outcome"] = json!(outcome);
    complete["raw"] = input::file_ref("codec.json", &bytes);
    output::emit(&complete)?;
    std::thread::sleep(Duration::from_millis(100));
    if !passed {
        return Err("codec population incomplete; original failure retained in codec.json".into());
    }
    Ok(())
}

#[test]
fn fixed_fixtures_preserve_independent_bytes_and_canonical_semantics() {
    let cases = [
        (
            "scalar-params",
            131,
            123,
            13,
            "dc9b0f64c0314b1b63a0fd8f968bfee8fa172db397ce1b16ea659c5861b5cd6e",
            "22626f99436997ebf88b8b78c0f1eb7ea275c2ac9fde08ea53436152bd67409b",
        ),
        (
            "byte-list",
            14627,
            14627,
            1,
            "7a5f0cc0128580e42013f1243adbb757bf21a03880bee9c011d89995a5550432",
            "7a5f0cc0128580e42013f1243adbb757bf21a03880bee9c011d89995a5550432",
        ),
        (
            "nested-record",
            2850,
            2850,
            6,
            "914e86a3ca85e2e180479d9b17a1f990fccacc8f235da970aa7b6cdf2078731a",
            "31d7b788d9e0b1febc723dab490b8f643060907020e5752b41404b3544ca65f4",
        ),
        (
            "string-64k",
            65540,
            65540,
            1,
            "c3d56e681749fe23d224d22e13f6e37fdf331ec060c434d30e272e5b89c0721f",
            "c3d56e681749fe23d224d22e13f6e37fdf331ec060c434d30e272e5b89c0721f",
        ),
        (
            "string-near-limit",
            122_884,
            122_884,
            1,
            "a9484011a23775c3aa1db93bdf18a55657c5b5a040a2ee661f167600f849a6c7",
            "a9484011a23775c3aa1db93bdf18a55657c5b5a040a2ee661f167600f849a6c7",
        ),
        (
            "escaped-unicode",
            98308,
            49156,
            1,
            "2247385277367578f40136bf9fc4c4b557e45a10f1d189bb792d90b449c3f655",
            "a10b665d190c71907c72ae580520d15dbbba44855a9c30efa0dd1e27da3daba6",
        ),
    ];
    for (family, input_bytes, output_bytes, arity, input_hash, output_hash) in cases {
        let fixture = Fixture::new(family).expect("owned type fixture");
        assert_eq!(
            (
                fixture.input.len(),
                fixture.expected.len(),
                fixture.types.len()
            ),
            (input_bytes, output_bytes, arity),
            "{family}"
        );
        assert_eq!(
            input::sha256(&fixture.input),
            format!("sha256:{input_hash}"),
            "{family}"
        );
        assert_eq!(
            input::sha256(&fixture.expected),
            format!("sha256:{output_hash}"),
            "{family}"
        );
        let (values, preflight) =
            preflight::verify(&fixture, ValueCodecLimits::default(), Instant::now())
                .expect("canonical semantics");
        assert_eq!(preflight["decode_calls"], "3");
        assert_eq!(preflight["encode_calls"], "3");
        drop(values);
        drop(fixture);
    }
}
