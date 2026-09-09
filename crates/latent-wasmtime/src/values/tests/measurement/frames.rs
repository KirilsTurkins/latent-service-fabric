use std::hint::black_box;

use latent_core::PlatformError;
use serde_json::{json, Value};
use wasmtime::component::Val;

use super::fixtures::Fixture;
use crate::values::{decode_params, encode_result, EncodedResult, ValueCodecLimits, MEDIA_TYPE};

#[derive(Default)]
pub(super) struct Batch {
    pub attempted: usize,
    pub completed: usize,
    pub successes: usize,
    pub observed: u64,
    pub failure: Option<Failure>,
}

pub(super) struct Failure {
    pub ordinal: usize,
    pub code: &'static str,
    pub message: String,
}

impl Batch {
    fn reject(&mut self, code: &'static str, message: String) {
        self.failure = Some(Failure {
            ordinal: self.attempted,
            code,
            message,
        });
    }

    fn error(&mut self, error: &PlatformError) {
        // Only a failed, incomplete population allocates a diagnostic message.
        self.reject(
            error.code.wire_code(),
            error.message.chars().take(1024).collect(),
        );
    }

    pub fn failure_json(&self, phase: &str) -> Value {
        self.failure.as_ref().map_or(Value::Null, |failure| {
            json!({
                "phase": phase, "ordinal": failure.ordinal.to_string(),
                "code": failure.code, "message": failure.message,
            })
        })
    }
}

// Ordinary helpers are also used for warmup. Only the two non-inlined wrappers
// in the parent module delimit measured allocation attribution.
pub(super) fn decode_loop(fixture: &Fixture, limits: ValueCodecLimits, count: usize) -> Batch {
    let mut batch = Batch::default();
    for _ in 0..count {
        batch.attempted += 1;
        let result = black_box(decode_params(
            black_box(&fixture.types),
            black_box(&fixture.input),
            black_box(MEDIA_TYPE),
            black_box(limits),
        ));
        batch.completed += 1;
        match &result {
            Ok(values) if values.len() == fixture.types.len() => {
                batch.successes += 1;
                batch.observed += values.len() as u64;
            }
            Ok(_) => batch.reject(
                "shape-mismatch",
                "decoded arity differs from fixture".to_owned(),
            ),
            Err(error) => batch.error(error),
        }
        // The complete owned result, including all nested values and any error,
        // is destroyed before returning from the measured allocation frame.
        drop(black_box(result));
        if batch.failure.is_some() {
            break;
        }
    }
    black_box(&batch);
    batch
}

pub(super) fn encode_loop(
    fixture: &Fixture,
    values: &[Val],
    limits: ValueCodecLimits,
    count: usize,
) -> Batch {
    let mut batch = Batch::default();
    for _ in 0..count {
        batch.attempted += 1;
        let result = black_box(encode_result(
            black_box(&fixture.types),
            black_box(values),
            black_box(limits),
        ));
        batch.completed += 1;
        match &result {
            Ok(EncodedResult::Returned(bytes)) if bytes.len() == fixture.expected.len() => {
                batch.successes += 1;
                batch.observed += bytes.len() as u64;
            }
            Ok(_) => batch.reject(
                "shape-mismatch",
                "encoded result kind or length differs from fixture".to_owned(),
            ),
            Err(error) => batch.error(error),
        }
        drop(black_box(result));
        if batch.failure.is_some() {
            break;
        }
    }
    black_box(&batch);
    batch
}
