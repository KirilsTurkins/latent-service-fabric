#![cfg(target_arch = "wasm32")]

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

const LOG_MESSAGE: &str = "echo invocation";

struct EchoCapsule;

impl Guest for EchoCapsule {
    fn echo(message: String) -> Result<String, EchoError> {
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
        // Logging is deliberately best effort: the declared echo result is never
        // replaced by a logging-capability failure.
        let _log_outcome = log::write(Level::Info, LOG_MESSAGE, &fields);

        result.map_err(|error| match error {
            MessageRejection::Empty => EchoError::EmptyMessage,
            MessageRejection::OverLimit => EchoError::MessageTooLarge,
        })
    }
}

export!(EchoCapsule);
