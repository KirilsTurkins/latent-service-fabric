//! Measured, strictly bounded standalone conformance. This is not a scale or soak gate.

#[cfg(target_os = "linux")]
#[path = "phase1_conformance/cases.rs"]
mod cases;
#[cfg(target_os = "linux")]
#[path = "phase1_conformance/evidence.rs"]
mod evidence;
#[cfg(target_os = "linux")]
#[path = "phase1_conformance/fixtures.rs"]
mod fixtures;
#[cfg(target_os = "linux")]
#[path = "phase1_conformance/harness.rs"]
mod harness;

#[cfg(target_os = "linux")]
#[tokio::test]
#[ignore = "requires explicit built node/components, runner identity, and adapter parity evidence"]
async fn phase1_bounded_child_conformance() {
    let output = std::path::PathBuf::from(
        std::env::var_os("LSF_PHASE1_OUTPUT_DIR").expect("required evidence output directory"),
    );
    assert!(output.is_absolute() && output.is_dir());
    let fixtures = fixtures::Fixtures::load();
    let work = latent_testkit::conformance::WorkCounter::with_limits(48, 224)
        .expect("fixed process profile limits");
    let mut harness = harness::Harness::new(output.clone(), work.clone());
    let mut evidence = evidence::Evidence::new(output, work, &harness.public_config, &fixtures);
    tokio::time::timeout(
        std::time::Duration::from_secs(65),
        cases::run(&mut harness, &mut evidence, &fixtures),
    )
    .await
    .expect("bounded driver watchdog");
    evidence.finish();
}
