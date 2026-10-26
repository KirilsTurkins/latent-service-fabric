//! Bounded trusted protocol state and continuations of an existing operation.
use super::{
    Arc, Charge, Kind, PlatformError, PoolAdmission, PoolCall, ProviderClient, ProviderPools,
};
use crate::broker::{io::IoLease, network::StreamScope, session::SessionCoreOwner};
use sha2::{Digest, Sha256};

/// Retain after the actual protocol objects it accounts for. Dropping a waiter
/// must never drop this charge while a socket/driver/parser still owns that state.
pub struct ProviderMetadata {
    _charge: Charge,
}

/// Fixed shared physical backing/bootstrap owner, charged to existing provider
/// metadata before opening the protected factory. Keep this AFTER the actual
/// descriptor and outstanding kernel ownership in bounded quarantine. A closed
/// fd, returned view or failed bootstrap is not permission to refund this owner.
/// This reservation alone cannot install or authenticate a kernel profile.
pub struct StreamKernelBacking {
    _metadata: ProviderMetadata,
    _pools: Arc<super::Inner>,
}

/// The exact original 512 KiB order-7 bank portion, never another allowance.
/// Trusted adapters must retain this affine charge after possible entry until
/// their original protected observation proves that bank physically returned.
/// The remaining bootstrap/descriptor owner is independent and stays retained.
pub struct StreamKernelBankCharge {
    _metadata: ProviderMetadata,
}

impl StreamKernelBacking {
    /// Partition the SAME atomic one-MiB admission before physical entry.
    /// No counter changes here, allocation, size argument or refund proof.
    pub fn partition_original_bank(&mut self) -> Result<StreamKernelBankCharge, PlatformError> {
        let charge = self._metadata._charge.partition_stream_bank()?;
        Ok(StreamKernelBankCharge {
            _metadata: ProviderMetadata { _charge: charge },
        })
    }
}

/// Original accepted work retained by a private kernel factory owner. This is
/// not a kernel identity, retirement certificate or provider-install permission.
/// There is no constructor from strings, scope words, serialized claims or an
/// arbitrary HostMemoryReservation. Keep it after the actual kernel handle.
pub struct StreamKernelOwnership {
    binding: [u64; 8],
    deadline: std::time::Instant,
    bytes: u64,
    // Rust drops fields in declaration order: actual memory/accounting owners
    // precede scope/request release and the final original I/O quiescence owner.
    memory: latent_core::budget::HostMemoryReservation,
    _scope: Arc<StreamScope>,
    _request: Arc<super::admission::Request>,
    io: IoLease,
}

impl StreamKernelOwnership {
    /// Private native framing of THIS original affine owner. These words are
    /// not a grant, public handle, liveness check or retirement certificate.
    /// There is no constructor from caller words or serialized identities.
    #[must_use]
    pub fn kernel_binding_words(&self) -> &[u64; 8] {
        &self.binding
    }
    #[must_use]
    pub fn deadline(&self) -> std::time::Instant {
        self.deadline
    }
    /// Exact original occupancy reservation. A native adapter must match TCP
    /// versus DNS before any constructor; a smaller owner cannot fund TCP.
    #[must_use]
    pub fn maximum_bytes(&self) -> u64 {
        self.bytes
    }
    /// Record actual physical allocation against the already-held original
    /// host reservation. This cannot change its size, identity or lifetime.
    pub fn confirm(&mut self) {
        self.memory.confirm();
    }
    /// A stopped operation cannot start another root. Failure does not consume
    /// this owner or refund anything; maintenance must retain it while physical
    /// work remains unproved, including after the response waiter disappears.
    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        self.io.checkpoint()
    }
}

impl PoolCall {
    /// Prepay one original TCP (96 KiB) or DNS (64 KiB) occupancy before entering
    /// a protected factory. Backing is a separate node/provider charge and is
    /// never refunded by dropping a connection view. The actual accepted call,
    /// session and provider epoch are retained; matching names are insufficient.
    pub fn reserve_stream_kernel_ownership(
        &self,
        scope: &Arc<StreamScope>,
        bytes: u64,
    ) -> Result<StreamKernelOwnership, PlatformError> {
        self.io.checkpoint()?;
        let provider = self.stream_request().client.epoch.registration.reference();
        if !matches!(bytes, 65_536 | 98_304)
            || provider.capability() != crate::broker::network::STREAM_CAPABILITY
            || provider.profile() != crate::broker::network::STREAM_PROFILE
            || !scope.with_session(|original| {
                self.io.with_session(|accepted| {
                    SessionCoreOwner::ptr_eq(&original.core, &accepted.core)
                })
            })
        {
            return Err(super::denied());
        }
        let memory = scope.reserve_host_memory(bytes)?;
        // Reuse the existing checked, never-wrapping incarnation issuer. This
        // is a new loan on the SAME accepted session, not a new activation or
        // provider. No guest Random call or ambient entropy grant is involved.
        let incarnation = crate::broker::session::next_incarnation()?;
        let digest = scope.with_session(|session| {
            let target = &session.core.plan.target;
            let fields = [
                target.tenant.0.as_str(),
                target.service.0.as_str(),
                target.revision.0.as_str(),
                target.release.0.as_str(),
                target.publication.as_str(),
                session.core.activation_id.0.as_str(),
                session.core.root_activation_id.0.as_str(),
                provider.capability(),
                provider.profile(),
                provider.configuration_digest(),
            ];
            let mut hash = Sha256::new();
            hash.update(b"lsf-stream-original-owner-v1\0");
            for (index, field) in fields.into_iter().enumerate() {
                hash.update([u8::try_from(index).expect("fixed scope field count")]);
                hash.update(
                    u64::try_from(field.len())
                        .expect("bounded original identity")
                        .to_le_bytes(),
                );
                hash.update(field.as_bytes());
            }
            hash.update(target.generation.0.to_le_bytes());
            hash.update(provider.configuration_epoch().to_le_bytes());
            hash.finalize()
        });
        let mut binding = [
            incarnation,
            self.stream_request().client.epoch.instance,
            self.stream_request().sequence,
            u64::from(self.stream_request().client.origin) + 1,
            0,
            0,
            0,
            0,
        ];
        for (word, encoded) in binding[4..].iter_mut().zip(digest.chunks_exact(8)) {
            *word = u64::from_le_bytes(encoded.try_into().expect("fixed SHA256 words"));
        }
        if binding.contains(&0) {
            return Err(super::capacity());
        }
        self.io.checkpoint()?;
        Ok(StreamKernelOwnership {
            binding,
            deadline: self.io.deadline(),
            bytes,
            memory,
            _scope: Arc::clone(scope),
            _request: self.retain_stream_request(),
            io: self.io.lease(),
        })
    }
}
impl ProviderPools {
    /// The proposed backing extent is 512 KiB; the full fixed one-MiB bootstrap
    /// reservation also covers producer/descriptor metadata only once its exact
    /// complete compiled cost is proved. This uses the existing per-reservation
    /// ceiling and original node quota. No caller-selected size or new budget.
    pub fn reserve_stream_kernel_backing(&self) -> Result<StreamKernelBacking, PlatformError> {
        let metadata = self.reserve_protocol_metadata(1024 * 1024)?;
        Ok(StreamKernelBacking {
            _metadata: metadata,
            _pools: Arc::clone(&self.inner),
        })
    }
    /// Reserve before allocating adapter configuration, TLS or decoder state.
    /// This is shared node accounting, not a claim about total process RSS.
    pub fn reserve_protocol_metadata(
        &self,
        bytes: usize,
    ) -> Result<ProviderMetadata, PlatformError> {
        self.inner.check()?;
        if bytes == 0 || bytes > 1024 * 1024 {
            return Err(super::capacity());
        }
        Ok(ProviderMetadata {
            _charge: self.inner.quotas.acquire(Kind::Metadata, bytes)?,
        })
    }
    /// A redirect cannot mint another activation, extend the timeout, or escape
    /// the original tenant/plan. Drop the old operation before awaiting this one.
    pub fn admit_followup<T: Send + 'static>(
        &self,
        client: &Arc<ProviderClient<T>>,
        previous: &PoolCall,
    ) -> Result<PoolAdmission, PlatformError> {
        if !previous.belongs_to(&self.inner) {
            return Err(super::denied());
        }
        previous.io().checkpoint()?;
        previous
            .io()
            .with_session(|session| self.admit_until(client, session, previous.io().deadline()))
    }
}
