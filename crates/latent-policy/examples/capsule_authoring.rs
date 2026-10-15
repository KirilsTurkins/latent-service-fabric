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
    if args.len() == 8 && args[0] == "fixture-sign-current-java-inputs" {
        return authoring::sign_current_java(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("current fixture source must be UTF-8")?,
            &args[3..],
        );
    }
    if args.len() == 9 && args[0] == "fixture-sign-current-java-with-negative" {
        return authoring::sign_current_java_with_negative(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("current fixture source must be UTF-8")?,
            &args[3..],
        );
    }
    if args.len() == 8 && args[0] == "fixture-sign-rebuilt-current-java-inputs" {
        return authoring::sign_rebuilt_current_java(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("rebuilt current fixture source must be UTF-8")?,
            &args[3..],
        );
    }
    if args.len() == 8 && args[0] == "fixture-sign-fresh-http-current-java-inputs" {
        return authoring::sign_fresh_http_current_java(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("fresh HTTP current fixture source must be UTF-8")?,
            &args[3..],
        );
    }
    if args.len() == 4 && args[0] == "fixture-sign-early-http-input" {
        return authoring::sign_early_http(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("early fixture source must be UTF-8")?,
            &args[3..],
        );
    }
    if args.len() == 8 && args[0] == "fixture-sign-native-memory-current-java-inputs" {
        return authoring::sign_native_memory_current_java(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("native memory current fixture source must be UTF-8")?,
            &args[3..],
        );
    }
    if args.len() == 4 && args[0] == "fixture-sign-rebuilt-early-http-input" {
        return authoring::sign_rebuilt_early_http(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("rebuilt early fixture source must be UTF-8")?,
            &args[3..],
        );
    }
    if args.len() == 4 && args[0] == "fixture-sign-reconstructed-early-http-input" {
        return authoring::sign_reconstructed_early_http(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("reconstructed early fixture source must be UTF-8")?,
            &args[3..],
        );
    }
    if args.len() == 8 && args[0] == "fixture-sign-reconstructed-current-java-inputs" {
        return authoring::sign_reconstructed_current_java(
            std::path::Path::new(&args[1]),
            args[2]
                .to_str()
                .ok_or("reconstructed current fixture source must be UTF-8")?,
            &args[3..],
        );
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
