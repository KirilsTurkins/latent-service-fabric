use super::{input, package, run, support};
#[path = "../random/component.rs"]
#[allow(dead_code, unused_imports)]
mod component;
#[path = "../random/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
use fixture::*;

#[tokio::test]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn generated_random_binding_and_reused_cell() {
    for language in super::languages() {
        let root = tempfile::tempdir().unwrap();
        let publication = package::publish(root.path(), &format!("{language}-random")).await;
        let f = Fixture::with_publication(None, Default::default(), None, Some(publication)).await;
        for (which, expected) in [(0, 32), (1, 8), (2, 10), (0, 32)] {
            let (mut request, control) = f.request("sdk-random", 0, 0, 0);
            input(&mut request, which, "", 0);
            assert_eq!(run(&f.backend, request, &control).await, expected);
            f.idle();
        }
    }
}

#[tokio::test]
#[ignore = "Requires actual compiled Java SecureRandom fixture"]
async fn standard_java_entropy_uses_original_system_provider_and_fresh_cells() {
    if !super::languages().contains(&"java") {
        return;
    }
    let root = tempfile::tempdir().unwrap();
    let publication = package::publish(root.path(), "java-random").await;
    let f = Fixture::with_publication(None, Default::default(), None, Some(publication)).await;
    for iteration in 0..2 {
        // Pinned TeaVM RandomGenerator.nextBoolean calls nextInt, consuming
        // four bytes. The numeric sequence therefore consumes 4+8+4+3+8.
        for (mode, expected, bytes) in [(3, 32, 32), (4, 32, 32), (5, 42, 0), (6, 42, 27)] {
            let before = f.provider.snapshot().generated_bytes;
            let (mut request, control) =
                f.request(&format!("java-entropy-{iteration}-{mode}"), 0, 0, 0);
            input(&mut request, mode, "", 0);
            assert_eq!(run(&f.backend, request, &control).await, expected);
            assert_eq!(f.provider.snapshot().generated_bytes - before, bytes);
            assert_eq!(control.budget.outstanding_reservations(), 0);
            f.idle();
        }
    }
}

#[tokio::test]
#[ignore = "Requires actual compiled Java SecureRandom fixture"]
async fn standard_java_entropy_preserves_provider_length_and_activation_budget_failures() {
    if !super::languages().contains(&"java") {
        return;
    }
    for (mode, ceiling, expected_bytes) in [(7, 16, 0), (8, 8, 8)] {
        let root = tempfile::tempdir().unwrap();
        let publication = package::publish(root.path(), "java-random").await;
        let limits = latent_capabilities::broker::random::RandomLimits {
            maximum_bytes_per_call: ceiling,
            maximum_bytes_per_activation: ceiling,
        };
        let f = Fixture::with_publication(None, limits, None, Some(publication)).await;
        for iteration in 0..2 {
            let before = f.provider.snapshot().generated_bytes;
            let (mut request, control) =
                f.request(&format!("java-entropy-failure-{mode}-{iteration}"), 0, 0, 0);
            input(&mut request, mode, "", 0);
            assert_eq!(run(&f.backend, request, &control).await, 42);
            assert_eq!(
                f.provider.snapshot().generated_bytes - before,
                expected_bytes
            );
            assert_eq!(control.budget.outstanding_reservations(), 0);
            f.idle();
        }
    }
}
