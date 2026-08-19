//! Rust implementation of `examples:echo/service@0.1.0`.

mod logic;

mod bindings {
    include!(concat!(env!("OUT_DIR"), "/echo_guest_bindings.rs"));
}

use bindings::exports::examples::echo::api::{EchoError, Guest};
use bindings::latent::context::context;
use bindings::latent::log::log::{self, Field, Level};
use logic::{bounded_utf8, classify_message, EchoOutcome, MAX_ACTIVATION_ID_BYTES};

struct EchoCapsule;

impl Guest for EchoCapsule {
    fn echo(message: String) -> Result<String, EchoError> {
        let outcome = classify_message(&message);
        let activation_id = bounded_utf8(&context::activation_id(), MAX_ACTIVATION_ID_BYTES);
        let fields = [
            Field {
                name: "activation.id".to_owned(),
                value: activation_id,
            },
            Field {
                name: "message.bytes".to_owned(),
                value: message.len().to_string(),
            },
            Field {
                name: "outcome".to_owned(),
                value: outcome.as_log_value().to_owned(),
            },
        ];

        // Logging is deliberately best effort. A declared logging-domain failure
        // must not alter the echo contract's own declared result.
        let _ = log::write(Level::Info, "echo invocation", &fields);

        match outcome {
            EchoOutcome::Success => Ok(message),
            EchoOutcome::EmptyMessage => Err(EchoError::EmptyMessage),
            EchoOutcome::MessageTooLarge => Err(EchoError::MessageTooLarge),
        }
    }
}

bindings::export!(EchoCapsule with_types_in bindings);
