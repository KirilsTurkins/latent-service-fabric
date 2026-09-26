use super::support;
use latent_core::{CapabilityId, ContractId, IncomingDeadline};
use latent_executor::{BoundImport, ExecutionBackend, GuestOutcome};
use latent_ingress::http::{
    self, HeaderView, HttpVersion, Outcome, RawHead, Scheme, TrustedContext,
};
use latent_manifest::ContractImport;
use latent_wasmtime::{ValueCodecLimits, WasmtimeComponentEngineFactory};
use std::time::{Duration, Instant};

#[tokio::test]
#[ignore = "requires the web-contract component built by contract CI"]
async fn real_web_contract_transfers_maximum_body_and_keeps_host_principal_on_reuse() {
    let bytes =
        std::fs::read(std::env::var_os("LSF_WEB_COMPONENT").expect("web fixture path")).unwrap();
    let mut artifact = support::artifact_bytes(bytes, &[http::CONTRACT]);
    artifact.manifest.world = ContractId("latent:web/application-service@0.1.0".into());
    artifact.manifest.imports = vec![ContractImport {
        contract: ContractId("latent:context/context@0.1.0".into()),
        optional: false,
    }];
    let mut configuration = support::config();
    configuration.hostcall_fuel = 2 * 1024 * 1024;
    configuration.value_codec_limits = ValueCodecLimits {
        max_input_bytes: http::MAX_WIRE_BYTES,
        max_output_bytes: http::MAX_WIRE_BYTES,
        max_nodes: http::MAX_JSON_NODES,
        max_string_bytes: 512 * 1024,
        max_lifted_bytes: 64 * 1024 * 1024,
        ..ValueCodecLimits::default()
    };
    let factory = WasmtimeComponentEngineFactory::new(configuration).unwrap();
    let backend = factory.create_backend_instance();
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap();
    let pool = http::HttpPool::new(1, http::EXCHANGE_RESERVATION_BYTES).unwrap();
    for (subject, path, expected) in [
        ("alice", "/maximum", http::MAX_RESPONSE_BODY),
        ("bob", "/", 0),
    ] {
        let cancellation = support::Cancellation::new(subject);
        let mut execution = support::request(
            prepared.clone(),
            &cancellation.id,
            http::CONTRACT,
            http::FUNCTION,
            b"[]",
            support::budget(),
        );
        execution.activation.principal.subject = subject.into();
        let context = TrustedContext::new(
            execution.activation.principal.clone(),
            execution.activation.trace.clone(),
        )
        .unwrap();
        let value = vec![255; 4000];
        let headers = [
            HeaderView {
                name: "host",
                value: b"example.test",
            },
            HeaderView {
                name: "x-data",
                value: &value,
            },
            HeaderView {
                name: "x-data",
                value: &value,
            },
            HeaderView {
                name: "x-data",
                value: &value,
            },
            HeaderView {
                name: "x-data",
                value: &value,
            },
            HeaderView {
                name: "x-forwarded-user",
                value: b"administrator",
            },
        ];
        let deadline = IncomingDeadline::new(
            Instant::now() + Duration::from_secs(5),
            support::now_millis() + 5000,
        );
        let invocation = pool
            .begin(
                RawHead {
                    version: HttpVersion::Http11,
                    method: "POST",
                    scheme: Scheme::Https,
                    authority: "example.test",
                    target: path,
                    headers: &headers,
                },
                deadline,
            )
            .unwrap()
            .finish(context)
            .unwrap()
            .into_invocation()
            .unwrap();
        execution.activation.input = invocation.input().to_vec();
        execution.activation.deadline_unix_millis = Some(invocation.deadline().unix_millis());
        execution.imports = vec![BoundImport {
            capability: CapabilityId("context".into()),
            contract: "latent:context/context@0.1.0".into(),
            opaque_handle: "activation-scoped-test-binding".into(),
        }];
        let outcome = support::run(&backend, execution, &cancellation)
            .await
            .unwrap();
        let GuestOutcome::Returned {
            output,
            output_media_type,
            ..
        } = outcome
        else {
            panic!("web outcome: {outcome:?}");
        };
        let mut delivery = invocation
            .complete(Outcome::Returned {
                bytes: &output,
                media_type: &output_media_type,
            })
            .unwrap();
        assert_eq!(delivery.cause(), http::DeliveryCause::Application);
        assert_eq!(delivery.remaining_body().unwrap().len(), expected);
        assert!(delivery.remaining_body().unwrap().iter().all(|b| *b == 255));
        assert_eq!(
            delivery
                .headers()
                .find(|h| h.name == "x-subject")
                .unwrap()
                .value,
            subject.as_bytes()
        );
        assert!(!delivery.headers().any(|h| h.name == "x-forwarded-user"));
        delivery.mark_headers_written().unwrap();
        delivery.advance(expected).unwrap();
        delivery.finish().unwrap();
        assert_eq!(pool.snapshot().reserved_bytes, 0);
        support::idle(&backend);
    }
}
