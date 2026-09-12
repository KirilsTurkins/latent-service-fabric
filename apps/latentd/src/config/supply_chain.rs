use super::{invalid, SupplyChainConfig};
use latent_core::PlatformError;
use latent_policy::supply_chain::{
    SupplyChainAuthority, SupplyChainPolicy, SystemSupplyChainClock,
};
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::sync::Arc;

pub(crate) enum SupplyChainSettings {
    TrustedLocal,
    Enforced {
        policy: Box<[u8]>,
        lease_seconds: u64,
    },
}
pub(super) fn derive(config: &SupplyChainConfig) -> Result<SupplyChainSettings, PlatformError> {
    match config {
        SupplyChainConfig::TrustedLocal => Ok(SupplyChainSettings::TrustedLocal),
        SupplyChainConfig::Enforced {
            policy_file,
            clock_lease_seconds,
        } => {
            if !(1..=5).contains(clock_lease_seconds) {
                return Err(invalid("supplyChain.clockLeaseSeconds"));
            }
            let mut bytes = Vec::new();
            File::open(policy_file)
                .map_err(|_| invalid("supplyChain.policyFile"))?
                .take(256 * 1024 + 1)
                .read_to_end(&mut bytes)
                .map_err(|_| invalid("supplyChain.policyFile"))?;
            SupplyChainPolicy::from_json(&bytes)?;
            Ok(SupplyChainSettings::Enforced {
                policy: bytes.into_boxed_slice(),
                lease_seconds: *clock_lease_seconds,
            })
        }
    }
}
impl SupplyChainSettings {
    pub(crate) const fn is_enforced(&self) -> bool {
        matches!(self, Self::Enforced { .. })
    }

    pub(crate) fn open(
        &self,
        data: &Path,
    ) -> Result<Option<Arc<SupplyChainAuthority>>, PlatformError> {
        match self {
            Self::TrustedLocal => Ok(None),
            Self::Enforced {
                policy,
                lease_seconds,
            } => {
                // A prior enforced catalog cannot bootstrap a new authority
                // after losing its independently persisted generation floors.
                let prior_enforced =
                    match std::fs::symlink_metadata(data.join("releases/ADMISSION_MODE")) {
                        Ok(_) => true,
                        Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => false,
                        Err(_) => return Err(invalid("supplyChain.persistedAuthorityUnreadable")),
                    };
                if prior_enforced
                    && (!data.join("supply-chain/INITIALIZED").is_file()
                        || !data.join("supply-chain/floor.json").is_file())
                {
                    return Err(invalid("supplyChain.persistedAuthorityMissing"));
                }
                Ok(Some(Arc::new(SupplyChainAuthority::open(
                    &data.join("supply-chain"),
                    SupplyChainPolicy::from_json(policy)?,
                    Arc::new(SystemSupplyChainClock),
                    *lease_seconds,
                )?)))
            }
        }
    }
}
