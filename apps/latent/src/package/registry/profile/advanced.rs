//! Closed CLI mappings to the existing reviewed OCI transport policy.
use super::{profile_error, Failure};
use latent_oci::{
    BearerIdentity, RegistryActions, RegistryAddressPolicy, RegistryCredentials,
    RegistryDestination, RegistryNetworkPolicy, RegistryResolution,
};
use serde::Deserialize;
use std::net::{IpAddr, SocketAddr};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Challenge {
    realm: String,
    service: String,
    identity: Identity,
    actions: Actions,
    pub addresses: Vec<SocketAddr>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Identity {
    tenant: String,
    principal: String,
    credential_epoch: u64,
}

#[derive(Deserialize)]
#[serde(rename_all = "kebab-case")]
enum Actions {
    Pull,
    PullPush,
}

impl Challenge {
    pub fn validate(&self) -> Result<(), Failure> {
        if self.realm.is_empty()
            || self.realm.len() > 512
            || self.service.is_empty()
            || self.service.len() > 256
            || self.identity.tenant.is_empty()
            || self.identity.tenant.len() > 128
            || self.identity.principal.is_empty()
            || self.identity.principal.len() > 256
            || self.identity.credential_epoch == 0
            || !self
                .identity
                .tenant
                .bytes()
                .chain(self.identity.principal.bytes())
                .all(|byte| byte.is_ascii_graphic())
            || self.addresses.len() > 16
        {
            return Err(profile_error());
        }
        Ok(())
    }

    pub fn bind(self, credentials: RegistryCredentials) -> Result<RegistryCredentials, Failure> {
        let RegistryCredentials::Basic { username, password } = credentials else {
            return Err(profile_error());
        };
        Ok(RegistryCredentials::BearerChallenge {
            realm: self.realm,
            service: self.service,
            identity: BearerIdentity {
                tenant: latent_core::TenantId(self.identity.tenant),
                principal: self.identity.principal,
                credential_epoch: self.identity.credential_epoch,
            },
            actions: match self.actions {
                Actions::Pull => RegistryActions::Pull,
                Actions::PullPush => RegistryActions::PullPush,
            },
            username,
            password,
            addresses: self.addresses,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Network {
    destinations: Vec<Destination>,
    maximum_redirects: usize,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Destination {
    origin: String,
    addresses: RegistryAddressPolicy,
    resolution: Resolution,
    content_prefixes: Vec<String>,
}

#[derive(Deserialize)]
#[serde(tag = "mode", rename_all = "camelCase", deny_unknown_fields)]
enum Resolution {
    Static {
        addresses: Vec<IpAddr>,
    },
    Dns {
        server: SocketAddr,
        #[serde(rename = "maximumTtlSeconds")]
        maximum_ttl_seconds: u32,
    },
}

impl Network {
    pub fn validate(&self) -> Result<(), Failure> {
        if self.destinations.is_empty() || self.destinations.len() > 8 || self.maximum_redirects > 3
        {
            return Err(profile_error());
        }
        for destination in &self.destinations {
            destination
                .addresses
                .validate()
                .map_err(|_| profile_error())?;
            if destination.origin.len() > 512
                || destination.content_prefixes.len() > 8
                || destination
                    .content_prefixes
                    .iter()
                    .any(|prefix| prefix.len() > 512)
            {
                return Err(profile_error());
            }
            match &destination.resolution {
                Resolution::Static { addresses }
                    if addresses.is_empty() || addresses.len() > 16 =>
                {
                    return Err(profile_error());
                }
                Resolution::Dns {
                    maximum_ttl_seconds,
                    ..
                } if !(1..=300).contains(maximum_ttl_seconds) => {
                    return Err(profile_error());
                }
                _ => (),
            }
        }
        Ok(())
    }
}

impl From<Network> for RegistryNetworkPolicy {
    fn from(value: Network) -> Self {
        Self {
            maximum_redirects: value.maximum_redirects,
            destinations: value
                .destinations
                .into_iter()
                .map(|destination| RegistryDestination {
                    origin: destination.origin,
                    addresses: destination.addresses,
                    content_prefixes: destination.content_prefixes,
                    resolution: match destination.resolution {
                        Resolution::Static { addresses } => {
                            RegistryResolution::Static { addresses }
                        }
                        Resolution::Dns {
                            server,
                            maximum_ttl_seconds,
                        } => RegistryResolution::Dns {
                            server,
                            maximum_ttl_seconds,
                        },
                    },
                })
                .collect(),
        }
    }
}
