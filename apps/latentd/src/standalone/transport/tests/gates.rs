use super::super::state::Kind;
use super::*;

#[test]
fn readiness_is_once_only_and_cancel_status_has_global_headroom() {
    let shared = state::Shared::new(configuration());
    let handle = TransportHandle {
        shared: Arc::clone(&shared),
    };
    assert!(!handle.snapshot().accepting);
    assert!(shared.acquire(Kind::Rpc { inspection: false }).is_err());
    handle.start_accepting().unwrap();
    let first = shared.acquire(Kind::Rpc { inspection: false }).unwrap();
    let second = shared.acquire(Kind::Rpc { inspection: false }).unwrap();
    assert_eq!(
        shared
            .acquire(Kind::Rpc { inspection: false })
            .err()
            .unwrap()
            .code(),
        tonic::Code::ResourceExhausted
    );
    let inspection = shared.acquire(Kind::Rpc { inspection: true }).unwrap();
    assert!(shared.acquire(Kind::Rpc { inspection: true }).is_err());
    assert_eq!(handle.snapshot().active_rpcs, 3);
    handle.stop_accepting();
    assert!(handle.start_accepting().is_err());
    drop((first, second, inspection));
    assert_eq!(handle.snapshot().active_rpcs, 0);
    assert!(shared.acquire(Kind::Rpc { inspection: true }).is_err());
}

#[test]
fn connection_and_control_job_guards_are_independent_and_nonqueued() {
    let shared = ready_shared();
    let connection = shared.acquire(Kind::Connection).unwrap();
    assert!(shared.acquire(Kind::Connection).is_err());
    let control = shared.acquire(Kind::ControlJob).unwrap();
    assert!(shared.acquire(Kind::ControlJob).is_err());
    assert_eq!(shared.snapshot().active_connections, 1);
    assert_eq!(shared.snapshot().active_control_jobs, 1);
    drop((connection, control));
    assert_eq!(shared.snapshot().active_connections, 0);
    assert_eq!(shared.snapshot().active_control_jobs, 0);
}

#[test]
fn malformed_configuration_is_rejected_before_listener_creation() {
    configuration().validate().unwrap();
    for case in 0..5 {
        let mut config = configuration();
        match case {
            0 => config.bind = "0.0.0.0:0".parse().unwrap(),
            1 => config.credentials.push(config.credentials[0].clone()),
            2 => config.maximum_rpcs = config.reserved_cancel_status_rpcs,
            3 => config.credentials[0].token = "bad token".to_owned(),
            _ => config.shutdown_timeout = Duration::ZERO,
        }
        assert!(config.validate().is_err());
    }
}
