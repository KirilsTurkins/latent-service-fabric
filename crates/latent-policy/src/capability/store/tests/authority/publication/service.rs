use super::*;

#[test]
#[expect(
    clippy::too_many_lines,
    reason = "same catalog checks a secrets decision and two distinct scoped service publications"
)]
fn only_the_explicit_service_publication_can_cross_the_policy_tenant_fence() {
    let fixture = Fixture::new();
    let publications = [
        publish(&fixture, "caller"),
        publish_scoped(&fixture, "target", "b"),
        publish_scoped(&fixture, "other", "b"),
    ];
    let proofs: Vec<_> = publications
        .iter()
        .map(|publication| {
            fixture
                .catalog
                .execution_eligibility_selected(
                    &publication.operation.record.as_ref().unwrap().release,
                    Some(&publication.publication.id),
                )
                .unwrap()
                .unwrap()
        })
        .collect();
    assert_eq!(proofs[0].release(), proofs[1].release());
    for service in [false, true] {
        let store = fixture.store(PolicyStoreLimits::default());
        let contract = if service {
            "latent:service/invoke@0.1.0"
        } else {
            "latent:secrets/reader@0.1.0"
        };
        let operation = if service { "call" } else { "read" };
        let mut document = policy();
        document["rules"][0]["publications"] =
            serde_json::json!([proofs[0].publication().as_str()]);
        document["rules"][0]["capability"] = contract.into();
        document["rules"][0]["operations"] = serde_json::json!([operation]);
        if service {
            document["rules"][0]["resources"] = serde_json::json!({"kind":"service","services":["callee"],"publications":[proofs[1].publication().as_str()]});
        }
        let expected = if service { 2 } else { 0 };
        mutate(
            &store,
            "p",
            if service { "service" } else { "secrets" },
            expected,
            Some(&serde_json::to_vec(&document).unwrap()),
        )
        .unwrap();
        let mut configured = binding();
        configured["capability"] = contract.into();
        let bytes = serde_json::to_vec(&configured).unwrap();
        store
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::ProviderBinding,
                    id: "binding",
                    operation_id: if service {
                        "service-binding"
                    } else {
                        "secrets-binding"
                    },
                    expected_revision: if service { 3 } else { 0 },
                    document: Some(&bytes),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
        let snapshot = store
            .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
            .unwrap();
        let actor = principal();
        let restriction = GrantRestriction::parse(br#"{"operations":[]}"#, contract).unwrap();
        let imported = vec![operation.into()];
        let digest = format!("sha256:{}", "2".repeat(64));
        let decision = snapshot
            .authorize(
                EvaluationInput {
                    principal: &actor,
                    service: "echo",
                    publication: proofs[0].publication().as_str(),
                    capability: contract,
                    operation,
                    resource: if service {
                        ResourceTarget::Service {
                            service: "callee",
                            publication: proofs[1].publication().as_str(),
                        }
                    } else {
                        ResourceTarget::Secrets {
                            reference: "test-key",
                        }
                    },
                },
                &CallRestrictions {
                    imported_operations: &imported,
                    deployment: &restriction,
                    provider_configuration: &restriction,
                    provider_profile: "local-secrets-v1",
                    configuration_digest: &digest,
                    configuration_epoch: 1,
                    remaining: CapabilityCeiling {
                        operations: 1,
                        input_bytes: 64,
                        output_bytes: 64,
                        wall_time_millis: 50,
                    },
                    input_bytes: 0,
                    output_bytes: 32,
                },
                &proofs[0],
            )
            .unwrap();
        let mut calls = 0;
        let result = store.with_current_dependencies(
            &decision,
            std::slice::from_ref(&proofs[1]),
            &mut |_, _| {
                calls += 1;
                Ok(())
            },
        );
        assert_eq!(result.is_ok(), service);
        assert_eq!(calls, usize::from(service));
        assert!(store
            .with_current_dependencies(
                &decision,
                std::slice::from_ref(&proofs[2]),
                &mut |_, _| panic!("other scoped publication must not pass")
            )
            .is_err());
    }
}
