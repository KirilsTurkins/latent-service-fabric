//! Identical auxiliary probe for pre/post artifact identity implementations.

mod artifact_identity_probe;

fn main() -> std::process::ExitCode {
    match artifact_identity_probe::run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(code) => {
            eprintln!("artifact-identity-probe: {code}");
            std::process::ExitCode::FAILURE
        }
    }
}
