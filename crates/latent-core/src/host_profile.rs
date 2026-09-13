//! Versioned data-only descriptions of host interfaces recognized by the runtime.
//!
//! A profile describes ABI recognition only. It does not grant a capability,
//! prove that a provider is configured, or allocate provider/runtime resources.

/// How a recognized host interface is supplied by the node.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostInterfaceBinding {
    /// Implemented directly by the fixed node runtime.
    BuiltIn,
    /// Requires an explicitly configured shared provider before preparation.
    Provider,
}

/// One exact versioned host interface in an ABI profile.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HostInterfaceSpec {
    pub interface: &'static str,
    pub package: &'static str,
    pub binding: HostInterfaceBinding,
}

/// Immutable host ABI profile shared by inspection and execution preparation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HostAbiProfile {
    pub id: &'static str,
    interfaces: &'static [HostInterfaceSpec],
}

impl HostAbiProfile {
    /// Returns every exact interface recognized by this profile.
    #[must_use]
    pub const fn interfaces(&self) -> &'static [HostInterfaceSpec] {
        self.interfaces
    }

    /// Resolve an exact versioned interface name. Same-name interfaces at a
    /// different version deliberately do not match.
    #[must_use]
    pub fn interface(&self, interface: &str) -> Option<&'static HostInterfaceSpec> {
        self.interfaces
            .iter()
            .find(|candidate| candidate.interface == interface)
    }
}

const PHASE3_V1_INTERFACES: [HostInterfaceSpec; 4] = [
    HostInterfaceSpec {
        interface: "latent:context/context@0.1.0",
        package: "latent:context",
        binding: HostInterfaceBinding::BuiltIn,
    },
    HostInterfaceSpec {
        interface: "latent:log/log@0.1.0",
        package: "latent:log",
        binding: HostInterfaceBinding::BuiltIn,
    },
    HostInterfaceSpec {
        interface: "latent:clock/monotonic@0.1.0",
        package: "latent:clock",
        binding: HostInterfaceBinding::BuiltIn,
    },
    HostInterfaceSpec {
        interface: "latent:clock/wall@0.1.0",
        package: "latent:clock",
        binding: HostInterfaceBinding::BuiltIn,
    },
];

/// First Phase 3 host-compatibility profile. It intentionally freezes the
/// already implemented context/log/clock ABI before provider interfaces are
/// admitted in later Phase 3 slices.
pub const PHASE3_HOST_ABI_V1: HostAbiProfile = HostAbiProfile {
    id: "lsf-host-abi-phase3-v1",
    interfaces: &PHASE3_V1_INTERFACES,
};

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn phase3_v1_is_exact_versioned_and_unique() {
        let mut seen = BTreeSet::new();
        for interface in PHASE3_HOST_ABI_V1.interfaces() {
            assert!(interface.interface.contains('@'));
            assert!(seen.insert(interface.interface));
            assert_eq!(interface.binding, HostInterfaceBinding::BuiltIn);
        }
        assert_eq!(seen.len(), 4);
    }

    #[test]
    fn lookup_does_not_accept_wrong_or_missing_versions() {
        assert!(PHASE3_HOST_ABI_V1
            .interface("latent:context/context@0.1.0")
            .is_some());
        assert!(PHASE3_HOST_ABI_V1
            .interface("latent:context/context@0.2.0")
            .is_none());
        assert!(PHASE3_HOST_ABI_V1
            .interface("latent:context/context")
            .is_none());
        assert!(PHASE3_HOST_ABI_V1
            .interface("latent:http/client@0.1.0")
            .is_none());
    }
}
