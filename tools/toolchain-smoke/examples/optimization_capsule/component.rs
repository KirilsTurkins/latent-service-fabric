#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "examples/optimization_capsule",
    world: "lsf:optimization/service@0.1.0",
    generate_all,
});

use exports::lsf::optimization::workloads::{Guest, TransformValue};
use latent_optimization_workloads as logic;

struct OptimizationCapsule;

impl Guest for OptimizationCapsule {
    fn echo(message: String) -> String {
        logic::echo(message).expect("optimization workload rejected")
    }

    fn compute(seed: u32, rounds: u32) -> u32 {
        logic::compute(seed, rounds).expect("optimization workload rejected")
    }

    fn transform(value: TransformValue) -> TransformValue {
        let output = logic::transform(logic::TransformValue {
            label: value.label,
            bytes: value.bytes,
            values: value.values,
        })
        .expect("optimization workload rejected");
        TransformValue {
            label: output.label,
            bytes: output.bytes,
            values: output.values,
        }
    }
}

export!(OptimizationCapsule);
