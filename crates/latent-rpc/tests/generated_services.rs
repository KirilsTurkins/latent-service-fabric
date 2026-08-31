use latent_rpc::control::v1::{
    audit_service_client::AuditServiceClient,
    audit_service_server::{AuditService, AuditServiceServer},
    binding_service_client::BindingServiceClient,
    binding_service_server::{BindingService, BindingServiceServer},
    capability_service_client::CapabilityServiceClient,
    capability_service_server::{CapabilityService, CapabilityServiceServer},
    contract_service_client::ContractServiceClient,
    contract_service_server::{ContractService, ContractServiceServer},
    deployment_service_client::DeploymentServiceClient,
    deployment_service_server::{DeploymentService, DeploymentServiceServer},
    node_service_client::NodeServiceClient,
    node_service_server::{NodeService, NodeServiceServer},
    policy_service_client::PolicyServiceClient,
    policy_service_server::{PolicyService, PolicyServiceServer},
    release_service_client::ReleaseServiceClient,
    release_service_server::{ReleaseService, ReleaseServiceServer},
    route_service_client::RouteServiceClient,
    route_service_server::{RouteService, RouteServiceServer},
    trigger_service_client::TriggerServiceClient,
    trigger_service_server::{TriggerService, TriggerServiceServer},
};
use latent_rpc::invocation::v1::{
    invocation_service_client::InvocationServiceClient,
    invocation_service_server::{InvocationService, InvocationServiceServer},
};
use tonic::transport::Channel;

fn assert_type<T: 'static>() {
    let _ = std::any::TypeId::of::<T>();
}

macro_rules! assert_server_surface {
    ($name:ident, $service:ident, $server:ident) => {
        #[allow(dead_code)]
        fn $name<T: $service + 'static>() {
            assert_type::<$server<T>>();
        }
    };
}

assert_server_surface!(assert_audit_server, AuditService, AuditServiceServer);
assert_server_surface!(assert_binding_server, BindingService, BindingServiceServer);
assert_server_surface!(
    assert_capability_server,
    CapabilityService,
    CapabilityServiceServer
);
assert_server_surface!(assert_contract_server, ContractService, ContractServiceServer);
assert_server_surface!(
    assert_deployment_server,
    DeploymentService,
    DeploymentServiceServer
);
assert_server_surface!(assert_node_server, NodeService, NodeServiceServer);
assert_server_surface!(assert_policy_server, PolicyService, PolicyServiceServer);
assert_server_surface!(assert_release_server, ReleaseService, ReleaseServiceServer);
assert_server_surface!(assert_route_server, RouteService, RouteServiceServer);
assert_server_surface!(assert_trigger_server, TriggerService, TriggerServiceServer);
assert_server_surface!(
    assert_invocation_server,
    InvocationService,
    InvocationServiceServer
);

#[test]
fn every_service_client_and_server_surface_is_generated() {
    assert_type::<AuditServiceClient<Channel>>();
    assert_type::<BindingServiceClient<Channel>>();
    assert_type::<CapabilityServiceClient<Channel>>();
    assert_type::<ContractServiceClient<Channel>>();
    assert_type::<DeploymentServiceClient<Channel>>();
    assert_type::<NodeServiceClient<Channel>>();
    assert_type::<PolicyServiceClient<Channel>>();
    assert_type::<ReleaseServiceClient<Channel>>();
    assert_type::<RouteServiceClient<Channel>>();
    assert_type::<TriggerServiceClient<Channel>>();
    assert_type::<InvocationServiceClient<Channel>>();
    assert!(!latent_rpc::FILE_DESCRIPTOR_SET.is_empty());
}
