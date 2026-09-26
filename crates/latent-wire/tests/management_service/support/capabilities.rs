use super::*;
use latent_capabilities::broker::ActivationCapabilityBroker;
use latent_policy::capability::{PolicyControlHandle, PolicyStore, PolicyStoreLimits};

pub(super) fn configure(
    adapter: ManagementServiceAdapter,
    root: &std::path::Path,
    artifacts: &Arc<DirectoryArtifactRepository>,
    deployments: &Arc<DirectoryDeploymentRepository>,
) -> (ManagementServiceAdapter, PolicyControlHandle) {
    let policies = Arc::new(
        PolicyStore::open(
            &root.join("policies"),
            PolicyStoreLimits {
                maximum_read_owners: 1,
                ..Default::default()
            },
            artifacts.lifecycle_authority(),
        )
        .unwrap(),
    );
    let control =
        PolicyControlHandle::new(policies.clone(), tokio::runtime::Handle::current(), 4).unwrap();
    let broker = Arc::new(
        ActivationCapabilityBroker::new(
            artifacts.lifecycle_authority(),
            policies,
            Arc::new(SystemActivationClock),
            latent_capabilities::broker::CapabilityBrokerLimits::default(),
        )
        .unwrap(),
    );
    let adapter = adapter
        .with_policy_control(control.clone())
        .unwrap()
        .with_capability_inspection(deployments.clone(), broker)
        .unwrap();
    (adapter, control)
}
