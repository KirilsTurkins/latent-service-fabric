#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: [
        "../../wit/platform/context",
        "../../wit/platform/log",
        "../../wit/platform/clock",
        "examples/capabilities_capsule",
    ],
    world: "tests:capabilities/service@0.1.0",
    generate_all,
});

use self::exports::tests::capabilities::api::{
    ClockReading, ContextSnapshot, Guest, LogObservation, WorkObservation,
};
use self::latent::clock::{monotonic, wall};
use self::latent::context::context;
use self::latent::log::log::{self, Field, Level};

struct CapabilitiesCapsule;

impl Guest for CapabilitiesCapsule {
    fn snapshot() -> ContextSnapshot {
        ContextSnapshot {
            activation: context::activation_id(),
            root: context::root_activation_id(),
            parent: context::parent_activation_id(),
            principal: context::principal(),
            trace: context::trace(),
            deadline: context::deadline_unix_millis(),
            metadata: context::metadata(),
            remaining: context::remaining_budget(),
        }
    }

    fn log_probe(message: String, fields: Vec<Field>) -> LogObservation {
        observe_log(&message, &fields)
    }

    fn log_twice(message: String, fields: Vec<Field>) -> Vec<LogObservation> {
        vec![
            observe_log(&message, &fields),
            observe_log(&message, &fields),
        ]
    }

    fn clocks() -> Vec<ClockReading> {
        let first = read_clock();
        let _accepted = log::write(Level::Info, "clock-step", &[]);
        let second = read_clock();
        let _accepted = log::write(Level::Info, "clock-step", &[]);
        vec![first, second, read_clock()]
    }

    fn work_observe() -> WorkObservation {
        let before = context::remaining_budget();
        // A single small allocation forces growth beyond the fixture's initial
        // memory. Keep it live across the observation without lengthy work.
        let mut bytes = vec![0_u8; 2 * 1024 * 1024];
        let mut checksum = 0_u32;
        for index in 0..1024 {
            bytes[index * 1024] = std::hint::black_box(1);
            checksum += u32::from(bytes[index * 1024]);
        }
        let logged = log::write(Level::Info, "bounded-work", &[]);
        let after = context::remaining_budget();
        std::hint::black_box(&bytes);
        WorkObservation {
            before,
            after,
            logged,
            checksum,
        }
    }
}

fn observe_log(message: &str, fields: &[Field]) -> LogObservation {
    let before = context::remaining_budget().log_bytes;
    let outcome = log::write(Level::Info, message, fields);
    let after = context::remaining_budget().log_bytes;
    LogObservation {
        before,
        outcome,
        after,
    }
}

fn read_clock() -> ClockReading {
    ClockReading {
        monotonic: monotonic::now_nanos(),
        wall: wall::now_unix_millis(),
    }
}

export!(CapabilitiesCapsule);
