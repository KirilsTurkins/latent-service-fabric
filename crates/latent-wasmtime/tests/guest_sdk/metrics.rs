use super::{input, package, run, support};
#[path = "../../../latent-control-store/tests/admission/support.rs"]
mod authority;
#[path = "../metrics/component.rs"]
#[allow(dead_code, unused_imports)]
mod component;
#[path = "../metrics/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
use fixture::*;

#[tokio::test]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn generated_metric_kinds_and_typed_failure() {
    for language in ["rust", "c"] {
        let root = tempfile::tempdir().unwrap();
        let publication = package::publish(root.path(), &format!("{language}-metrics")).await;
        let mut f =
            Fixture::with_publication(Default::default(), config(), None, Some(publication)).await;
        for (which, name, expected) in [
            (0, "requests", 1),
            (1, "inflight", 1),
            (2, "temperature", 1),
            (3, "latency", 1),
            (0, "latent.system", 10),
        ] {
            let (mut request, control) = f.request("sdk-metrics", serde_json::json!(null), 0, 0);
            input(&mut request, which, name, 0);
            assert_eq!(run(&f.backend, request, &control).await, expected);
            f.idle();
        }
        f.exporter.take().unwrap().shutdown().await.unwrap();
    }
}
