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
    if (4..=5).contains(&args.len()) && args[0] == "demo-check-stale-proofs" {
        return authoring::check_stale_proofs(
            std::path::Path::new(&args[1]),
            std::path::Path::new(&args[2]),
            &args[3..],
        );
    }
    if args.len() == 2 && args[0] == "fixture-tls" {
        return fixture_tls::create(std::path::Path::new(&args[1]));
    }
    if args.len() < 3
        || !matches!(args[0].to_str(), Some("demo-sign" | "demo-sign-separated"))
        || args.len() > 18
    {
        return Err("usage: capsule_authoring <demo-sign|demo-sign-separated> <new-private-output> <build-directory>... (at most 16 builds), or demo-check-stale-proofs <new-private-output> <policy> <signed-package-directory>... (at most 2 packages); development qualification only".into());
    }
    if args[0] == "demo-sign-separated" {
        authoring::sign_demo_separated(std::path::Path::new(&args[1]), &args[2..])
    } else {
        authoring::sign_demo(std::path::Path::new(&args[1]), &args[2..])
    }
}
