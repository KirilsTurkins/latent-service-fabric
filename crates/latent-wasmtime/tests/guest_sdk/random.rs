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
    for language in ["rust", "c"] {
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
