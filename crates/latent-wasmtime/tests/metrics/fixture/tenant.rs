use super::*;
impl Fixture {
    /// Same component bytes, broker, factory, exporter and physical cell; separate
    /// catalog publication, policy and invocation plan for the other tenant.
    pub async fn other_tenant(&self) -> (ResolvedRevision, PreparedComponent) {
        let mut artifact = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
        artifact.manifest.execution.resource_budget_ceiling = support::budget();
        artifact.manifest.metadata.tenant = None;
        artifact.manifest.imports.push(ContractImport {
            contract: ContractId(component::CAP.into()),
            optional: false,
        });
        let receipt = self
            .catalog
            .publish_managed(
                ReleaseMutationContext {
                    scope: LifecycleScope::Tenant(TenantId("other".into())),
                    actor: ReleaseActor {
                        subject: "broker-test".into(),
                        kind: ReleaseActorKind::Host,
                    },
                    operation: Some(ReleaseOperationPrecondition {
                        operation_id: "publish-other".into(),
                        expected_generation: 0,
                    }),
                },
                ManagedPublicationUpload::Package(authority::upload(&artifact)),
                &mut |_| Ok(()),
            )
            .await
            .unwrap();
        let publication = self
            .catalog
            .execution_eligibility_selected(&self.revision.release, Some(&receipt.publication.id))
            .unwrap()
            .unwrap();
        configuration::install(
            &self.policies,
            &publication,
            &self.provider.reference(),
            false,
            "other",
        );
        let mut revision = self.revision.clone();
        revision.target.tenant = TenantId("other".into());
        revision.publication = Some(receipt.publication.id);
        let plan = configuration::compile(
            &self.broker,
            &revision,
            &publication,
            &self.provider.reference(),
        );
        self.plans.0.lock().unwrap().push(plan);
        let mut key = self.factory.preparation_key(revision.release.clone());
        key.publication = revision.publication.clone();
        let prepared = self
            .backend
            .prepare_ready_from_repository(self.catalog.clone(), key)
            .await
            .unwrap()
            .descriptor()
            .clone();
        (revision, prepared)
    }
}
