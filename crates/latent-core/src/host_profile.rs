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
    /// Authoritative immutable source, shared with bounded semantic validation.
    pub wit: &'static str,
    /// Only freestanding async functions are selected; no implicit future/stream support.
    pub asynchronous: bool,
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

    /// Visit a canonical domain-separated identity without allocating or choosing
    /// a hash implementation. Native/prepared owners hash these bytes with SHA-256.
    /// Mutable grants and credentials deliberately do not enter this identity.
    pub fn visit_identity_bytes(&self, mut write: impl FnMut(&[u8])) {
        write(b"lsf-host-abi-profile-v1\0");
        write(&(self.id.len() as u64).to_le_bytes());
        write(self.id.as_bytes());
        write(&(self.interfaces.len() as u64).to_le_bytes());
        for item in self.interfaces {
            for value in [item.interface, item.package] {
                write(&(value.len() as u64).to_le_bytes());
                write(value.as_bytes());
            }
            write(&[
                match item.binding {
                    HostInterfaceBinding::BuiltIn => 0,
                    HostInterfaceBinding::Provider => 1,
                },
                u8::from(item.asynchronous),
            ]);
            write(&(item.wit.len() as u64).to_le_bytes());
            write(item.wit.as_bytes());
        }
    }
}

const PHASE3_V1_INTERFACES: [HostInterfaceSpec; 4] = [
    HostInterfaceSpec {
        interface: "latent:context/context@0.1.0",
        package: "latent:context",
        binding: HostInterfaceBinding::BuiltIn,
        wit: include_str!("../../../wit/platform/context/package.wit"),
        asynchronous: false,
    },
    HostInterfaceSpec {
        interface: "latent:log/log@0.1.0",
        package: "latent:log",
        binding: HostInterfaceBinding::BuiltIn,
        wit: include_str!("../../../wit/platform/log/package.wit"),
        asynchronous: false,
    },
    HostInterfaceSpec {
        interface: "latent:clock/monotonic@0.1.0",
        package: "latent:clock",
        binding: HostInterfaceBinding::BuiltIn,
        wit: include_str!("../../../wit/platform/clock/package.wit"),
        asynchronous: false,
    },
    HostInterfaceSpec {
        interface: "latent:clock/wall@0.1.0",
        package: "latent:clock",
        binding: HostInterfaceBinding::BuiltIn,
        wit: include_str!("../../../wit/platform/clock/package.wit"),
        asynchronous: false,
    },
];

/// First Phase 3 host-compatibility profile. It intentionally freezes the
/// already implemented context/log/clock ABI before provider interfaces are
/// admitted in later Phase 3 slices.
pub const PHASE3_HOST_ABI_V1: HostAbiProfile = HostAbiProfile {
    id: "lsf-host-abi-phase3-v1",
    interfaces: &PHASE3_V1_INTERFACES,
};

const PHASE3_V2_INTERFACES: [HostInterfaceSpec; 11] = [
    PHASE3_V1_INTERFACES[0],
    PHASE3_V1_INTERFACES[1],
    PHASE3_V1_INTERFACES[2],
    PHASE3_V1_INTERFACES[3],
    HostInterfaceSpec {
        interface: "latent:random/random@0.1.0",
        package: "latent:random",
        binding: HostInterfaceBinding::Provider,
        wit: include_str!("../../../wit/platform/random/package.wit"),
        asynchronous: false,
    },
    HostInterfaceSpec {
        interface: "latent:blob/blob@0.1.0",
        package: "latent:blob",
        binding: HostInterfaceBinding::Provider,
        wit: include_str!("../../../wit/platform/blob/package.wit"),
        asynchronous: false,
    },
    HostInterfaceSpec {
        interface: "latent:secrets/reader@0.1.0",
        package: "latent:secrets",
        binding: HostInterfaceBinding::Provider,
        wit: include_str!("../../../wit/platform/secrets/package.wit"),
        asynchronous: false,
    },
    HostInterfaceSpec {
        interface: "latent:events/publisher@0.2.0",
        package: "latent:events",
        binding: HostInterfaceBinding::Provider,
        wit: include_str!("../../../wit/platform/events-v2/package.wit"),
        asynchronous: false,
    },
    HostInterfaceSpec {
        interface: "latent:http/client@0.2.0",
        package: "latent:http",
        binding: HostInterfaceBinding::Provider,
        wit: include_str!("../../../wit/platform/http-v2/package.wit"),
        asynchronous: true,
    },
    HostInterfaceSpec {
        interface: "latent:telemetry/custom@0.1.0",
        package: "latent:telemetry",
        binding: HostInterfaceBinding::Provider,
        wit: include_str!("../../../wit/platform/telemetry/package.wit"),
        asynchronous: false,
    },
    HostInterfaceSpec {
        interface: "latent:service/invoke@0.1.0",
        package: "latent:service",
        binding: HostInterfaceBinding::Provider,
        wit: include_str!("../../../wit/platform/invocation/package.wit"),
        asynchronous: true,
    },
];

/// Recognized Phase 3 provider contracts. Recognition is not provider availability:
/// production preparation still requires actual installed bindings and current grants.
pub const PHASE3_HOST_ABI_V2: HostAbiProfile = HostAbiProfile {
    id: "lsf-host-abi-phase3-v2",
    interfaces: &PHASE3_V2_INTERFACES,
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

    #[test]
    fn v2_preserves_every_builtin_and_selects_only_explicit_async_interfaces() {
        for old in PHASE3_HOST_ABI_V1.interfaces() {
            assert_eq!(PHASE3_HOST_ABI_V2.interface(old.interface), Some(old));
        }
        let names: BTreeSet<_> = PHASE3_HOST_ABI_V2
            .interfaces()
            .iter()
            .map(|s| s.interface)
            .collect();
        assert_eq!(names.len(), PHASE3_HOST_ABI_V2.interfaces().len());
        let asynchronous: Vec<_> = PHASE3_HOST_ABI_V2
            .interfaces()
            .iter()
            .filter(|s| s.asynchronous)
            .map(|s| s.interface)
            .collect();
        assert_eq!(
            asynchronous,
            ["latent:http/client@0.2.0", "latent:service/invoke@0.1.0"]
        );
        for unsupported in [
            "latent:http/client@0.1.0",
            "latent:events/publisher@0.1.0",
            "latent:state/key-value@0.1.0",
            "wasi:filesystem/types@0.2.0",
        ] {
            assert!(PHASE3_HOST_ABI_V2.interface(unsupported).is_none());
        }
    }

    #[test]
    fn canonical_identity_changes_with_version_and_bounds_its_data() {
        let identity = |profile: HostAbiProfile| {
            let mut bytes = Vec::new();
            profile.visit_identity_bytes(|part| bytes.extend_from_slice(part));
            bytes
        };
        let current = identity(PHASE3_HOST_ABI_V2);
        assert!(current.len() < 32 * 1024);
        assert_ne!(current, identity(PHASE3_HOST_ABI_V1));
        let mut renamed = PHASE3_HOST_ABI_V2;
        renamed.id = "lsf-host-abi-phase3-v3";
        assert_ne!(current, identity(renamed));
    }
}
