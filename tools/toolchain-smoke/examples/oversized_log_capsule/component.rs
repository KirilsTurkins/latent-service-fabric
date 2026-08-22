#![cfg(target_arch = "wasm32")]

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
use self::latent::log::log::{self, Level};

struct OversizedLogCapsule;

impl Guest for OversizedLogCapsule {
    fn echo(message: String) -> Result<String, EchoError> {
        let _ = log::write(Level::Info, &message, &[]);
        Ok(message)
    }
}

export!(OversizedLogCapsule);
