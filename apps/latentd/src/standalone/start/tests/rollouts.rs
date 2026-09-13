mod canary;
pub(super) mod fixtures;
mod recovery;
mod rollback;
use super::*;
use latent_audit::AuditLimits;
use latent_control_store::rollouts::RolloutLimits;
use latent_rollout::CoordinatorLimits;
use latent_wire::management::proto;
use std::time::Duration;

#[test]
fn manual_owner_starts_and_joins_with_one_control_blocking_thread() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .max_blocking_threads(1)
        .build()
        .unwrap();
    runtime.block_on(async {
        let directory = TempDir::new().unwrap();
        for _ in 0..2 {
            let mut settings = settings(&directory);
            settings.audit = Some(AuditLimits::default());
            settings.rollouts = Some(crate::config::RolloutSettings {
                store: RolloutLimits::default(),
                coordinator: CoordinatorLimits::default(),
                canary: None,
            });
            settings.shutdown_grace = Duration::from_secs(5);
            let node = super::super::StandaloneNode::start(
                settings,
                runtime.handle().clone(),
                crate::standalone::RuntimeThreads::default(),
            )
            .await
            .unwrap();
            let endpoint = format!("http://{}", node.endpoint());
            let mut client = proto::rollout_service_client::RolloutServiceClient::connect(endpoint)
                .await
                .unwrap();
            let mut request = tonic::Request::new(proto::GetRolloutRequest {
                id: "missing".into(),
            });
            request.metadata_mut().insert(
                "authorization",
                "Bearer test-token-000000000000000000000000000000"
                    .parse()
                    .unwrap(),
            );
            request.set_timeout(Duration::from_secs(5));
            assert!(client
                .get_rollout(request)
                .await
                .unwrap()
                .into_inner()
                .status
                .is_none());
            let inventory = node.inventory().unwrap();
            assert!(inventory
                .topology
                .entries
                .iter()
                .any(|row| row.name == "rollout-coordinator" && row.active_count == Some(1)));
            drop(client);
            let report = node.shutdown().await.unwrap();
            assert!(report.clean);
            assert!(report.rollouts.unwrap().clean());
            assert!(report.audit.unwrap().worker_joined);
        }
    });
    runtime.shutdown_timeout(Duration::from_secs(5));
}

#[tokio::test]
async fn configured_rollouts_cannot_compose_without_their_owner() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    let catalogs = Catalogs::open(&settings).await.unwrap();
    settings.rollouts = Some(crate::config::RolloutSettings {
        store: RolloutLimits::default(),
        coordinator: CoordinatorLimits::default(),
        canary: None,
    });
    assert_eq!(
        super::super::StandaloneNode::compose(
            &mut settings,
            &catalogs,
            Arc::new(SystemActivationClock)
        )
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
}
