//! Explicit local-demo publisher/builder trust, using the real admission path.
//! This is never production trust and is not a compiler or a provenance oracle.
#[path = "capsule_authoring/mod.rs"]
mod authoring;
#[path = "capsule_authoring/fixture_tls.rs"]
mod fixture_tls;

fn main() {
    if let Err(error) = run() {
        eprintln!("capsule demo signing failed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    if args.len() == 2 && args[0] == "fixture-tls" {
        return fixture_tls::create(std::path::Path::new(&args[1]));
    }
    if args.len() < 3 || args[0] != "demo-sign" || args.len() > 18 {
        return Err("usage: capsule_authoring demo-sign <new-private-output> <build-directory>... (at most 16 builds); creates short-lived isolated demo trust only".into());
    }
    authoring::sign_demo(std::path::Path::new(&args[1]), &args[2..])
}
