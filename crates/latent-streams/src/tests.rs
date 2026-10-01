use crate::*;
use latent_network::AddressPolicy;
use latent_policy::capability::{StreamEndpoint, StreamTransport};

#[cfg(unix)]
mod currentness;
#[cfg(target_os = "linux")]
mod dns;
#[cfg(unix)]
mod fixture;
#[cfg(unix)]
mod lifecycle;
#[cfg(unix)]
mod maintenance;
#[cfg(unix)]
mod sockets;
#[cfg(unix)]
mod uncertainty;

fn config() -> StreamProviderConfig {
    StreamProviderConfig {
        format_version: 1,
        profile: latent_capabilities::broker::network::STREAM_PROFILE.into(),
        destinations: vec![StreamDestination {
            endpoint: StreamEndpoint {
                host: "127.0.0.1".into(),
                port: 25,
                transport: StreamTransport::Tcp,
            },
            addresses: AddressPolicy {
                networks: vec!["127.0.0.1/32".parse().unwrap()],
                special_addresses: vec!["127.0.0.1".parse().unwrap()],
            },
            resolution: StreamResolution::Static {
                addresses: vec!["127.0.0.1".parse().unwrap()],
            },
        }],
        limits: StreamLimits::default(),
    }
}

#[test]
fn opaque_transport_requires_exact_special_address_authority() {
    let mut config = config();
    assert!(config.validate().is_ok());
    config.destinations[0].addresses.special_addresses.clear();
    assert_eq!(
        config.validate().unwrap_err().code,
        StreamErrorCode::InvalidInput
    );
    config.destinations[0]
        .addresses
        .special_addresses
        .push("127.0.0.1".parse().unwrap());
    config.destinations[0].resolution = StreamResolution::Static {
        addresses: vec!["169.254.169.254".parse().unwrap()],
    };
    assert_eq!(
        config.validate().unwrap_err().code,
        StreamErrorCode::InvalidInput
    );
}

#[test]
fn unimplemented_host_tls_is_never_silently_replaced_with_tcp() {
    let mut config = config();
    config.destinations[0].endpoint.transport = StreamTransport::HostTls;
    assert_eq!(
        config.validate().unwrap_err().code,
        StreamErrorCode::Unsupported
    );
}
