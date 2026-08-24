#![cfg(target_arch = "wasm32")]

#[path = "../echo_capsule/logic.rs"]
mod logic;

wit_bindgen::generate!({
    path: [
        "../../wit/platform/context",
        "../../wit/platform/log",
        "../../examples/echo-contract/wit",
    ],
    world: "examples:echo/service@0.1.0",
    generate_all,
});

use self::exports::examples::echo::api::{EchoError, Guest};
use self::latent::context::context;
use self::latent::log::log::{self, Field, Level};
use logic::{MessageRejection, MAX_LOG_ACTIVATION_ID_BYTES};

const TRAP_MODE: &str = "__latent_test_trap";
const DELAYED_TRAP_MODE: &str = "__latent_test_delayed_trap";
const INFINITE_MODE: &str = "__latent_test_infinite";
const MEMORY_MODE: &str = "__latent_test_memory";
const DELAYED_ECHO_PREFIX: &str = "__latent_test_delayed_echo:";
const LOG_MESSAGE: &str = "containment fixture invocation";
const MEMORY_CHUNK_BYTES: usize = 64 * 1024;
const CONTROLLED_DELAY_ITERATIONS: u64 = 2_000_000;

struct ContainmentCapsule;

impl Guest for ContainmentCapsule {
    fn echo(message: String) -> Result<String, EchoError> {
        if let Some(delayed_message) = message.strip_prefix(DELAYED_ECHO_PREFIX) {
            controlled_delay();
            return normal_echo(delayed_message.to_owned());
        }

        match message.as_str() {
            TRAP_MODE => panic!("controlled containment fixture trap"),
            DELAYED_TRAP_MODE => {
                controlled_delay();
                panic!("controlled delayed containment fixture trap");
            }
            INFINITE_MODE => infinite_guest_loop(),
            MEMORY_MODE => {
                controlled_delay();
                exhaust_guest_memory();
            }
            _ => normal_echo(message),
        }
    }
}

fn normal_echo(message: String) -> Result<String, EchoError> {
    let message_bytes = message.len();
    let result = logic::echo(message);
    let activation_id = context::activation_id();
    let outcome = match &result {
        Ok(_) => "success",
        Err(MessageRejection::Empty) => "empty-message",
        Err(MessageRejection::OverLimit) => "message-too-large",
    };
    let fields = [
        Field {
            name: "activation_id".to_owned(),
            value: logic::bounded_utf8_prefix(&activation_id, MAX_LOG_ACTIVATION_ID_BYTES)
                .to_owned(),
        },
        Field {
            name: "message_bytes".to_owned(),
            value: message_bytes.to_string(),
        },
        Field {
            name: "outcome".to_owned(),
            value: outcome.to_owned(),
        },
    ];
    let _log_outcome = log::write(Level::Info, LOG_MESSAGE, &fields);

    result.map_err(|error| match error {
        MessageRejection::Empty => EchoError::EmptyMessage,
        MessageRejection::OverLimit => EchoError::MessageTooLarge,
    })
}

#[inline(never)]
fn controlled_delay() {
    let mut counter = 0_u64;
    while counter < CONTROLLED_DELAY_ITERATIONS {
        counter = counter.wrapping_add(1);
        std::hint::black_box(counter);
    }
}

#[inline(never)]
fn infinite_guest_loop() -> ! {
    let mut counter = 0_u64;
    loop {
        counter = counter.wrapping_add(1);
        std::hint::black_box(counter);
    }
}

#[inline(never)]
fn exhaust_guest_memory() -> ! {
    let mut chunks: Vec<Vec<u8>> = Vec::new();
    loop {
        let mut chunk = vec![0_u8; MEMORY_CHUNK_BYTES];
        chunk[0] = 1;
        chunk[MEMORY_CHUNK_BYTES - 1] = 1;
        chunks.push(chunk);
        std::hint::black_box(&chunks);
    }
}

export!(ContainmentCapsule);
