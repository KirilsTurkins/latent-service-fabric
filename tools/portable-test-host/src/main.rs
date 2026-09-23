//! Reuses the production backend and value codec; never instantiates a node.

mod request;
mod runtime;

use std::io::{Read, Write};

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let result = execute().await.unwrap_or_else(|code| {
        serde_json::json!({"schemaVersion":"latent.dev.portable-result.v1",
            "environment":"portable","category":"local-error","code":code,
            "outcomeKnown":true,"productionNode":false})
    });
    let failed = result["category"] == "local-error";
    let mut stdout = std::io::stdout().lock();
    if serde_json::to_writer(&mut stdout, &result).is_err() || writeln!(stdout).is_err() {
        std::process::exit(2);
    }
    if failed {
        std::process::exit(2);
    }
}

async fn execute() -> Result<serde_json::Value, &'static str> {
    let mut input = Vec::new();
    std::io::stdin()
        .take(32 * 1024 * 1024 + 1)
        .read_to_end(&mut input)
        .map_err(|_| "request-read")?;
    if input.len() > 32 * 1024 * 1024 {
        return Err("request-byte-limit");
    }
    let selected: request::Request =
        serde_json::from_slice(&input).map_err(|_| "invalid-request")?;
    selected.validate()?;
    runtime::run(selected).await
}
