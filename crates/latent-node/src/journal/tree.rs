//! Bounded read-only projection, sharing the journal's retention and lock.
use super::{error, LocalActivationJournal};
use latent_activation::RetainedActivationOutcome;
use latent_core::{
    diagnostic::ActivationDiagnostic, ActivationId, ActivationPhase, ActivationTerminalState,
    PlatformError, PlatformErrorCode, TenantId,
};
use sha2::{Digest, Sha256};
use std::fmt::Write as _;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

pub const MAXIMUM_TREE_NODES: usize = 128;
pub const MAXIMUM_TREE_BYTES: usize = 64 * 1024;
const MAXIMUM_ID_BYTES: usize = 512;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationTreeNode {
    pub activation_id: ActivationId,
    pub parent_activation_id: Option<ActivationId>,
    pub root_activation_id: ActivationId,
    pub phase: ActivationPhase,
    pub terminal_state: Option<ActivationTerminalState>,
    pub last_updated_unix_millis: u64,
    pub diagnostic: Option<ActivationDiagnostic>,
    pub diagnostic_is_terminal: bool,
    pub principal_kind: latent_core::PrincipalKind,
    pub caller_service: Option<latent_core::ServiceId>,
    pub granted_budget: Option<latent_core::ResourceBudget>,
    pub effective_deadline_unix_millis: Option<u64>,
    pub target_service: latent_core::ServiceId,
    pub received_at_unix_millis: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationTreePage {
    pub nodes: Vec<ActivationTreeNode>,
    pub next_page_token: Option<String>,
    /// False is deliberately indistinguishable for missing, evicted and foreign
    /// anchors. It never proves that an activation or external effect is absent.
    pub history_available: bool,
    pub cursor_expired: bool,
}

pub(super) fn epoch() -> [u8; 32] {
    static NEXT: AtomicU64 = AtomicU64::new(1);
    let mut hash = Sha256::new();
    hash.update(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
            .to_le_bytes(),
    );
    hash.update(std::process::id().to_le_bytes());
    hash.update(NEXT.fetch_add(1, Ordering::Relaxed).to_le_bytes());
    hash.finalize().into()
}

fn hex_digest(digest: &[u8]) -> String {
    let mut value = String::with_capacity(64);
    for byte in digest {
        let _ = write!(value, "{byte:02x}");
    }
    value
}

impl latent_core::diagnostic::ActivationDiagnosticSink for LocalActivationJournal {
    fn record(
        &self,
        tenant: &TenantId,
        activation: &ActivationId,
        diagnostic: ActivationDiagnostic,
    ) {
        // Fixed-size numeric snapshot; no event, string, payload or task.
        let mut state = self.inner.lock();
        if let Some(record) = state
            .records
            .get_mut(activation)
            .filter(|r| &r.tenant == tenant)
        {
            record.observed_diagnostic = Some(diagnostic);
        }
    }
}

impl LocalActivationJournal {
    /// Caller must already authorize tenant operator scope. Each index lookup
    /// and returned edge is additionally scoped to that tenant under one lock.
    /// The serial horizon freezes membership, not mutable execution outcomes.
    // Keep scope, membership and bounded projection under one observed lock.
    #[allow(clippy::too_many_lines)]
    pub fn inspect_tree(
        &self,
        tenant: &TenantId,
        anchor: &ActivationId,
        page_size: usize,
        token: Option<&str>,
    ) -> Result<ActivationTreePage, PlatformError> {
        self.validate_query(tenant, anchor)?;
        if tenant.0.len() > MAXIMUM_ID_BYTES
            || anchor.0.len() > MAXIMUM_ID_BYTES
            || page_size > MAXIMUM_TREE_NODES
            || token.is_some_and(|token| token.len() > 160)
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-activation-tree-query",
            ));
        }
        let mut state = self.inner.lock();
        state.expire(
            self.inner.clock.monotonic_now(),
            self.inner.config.terminal_retention,
        );
        let Some(record) = state
            .records
            .get(anchor)
            .filter(|record| &record.tenant == tenant)
        else {
            return Ok(ActivationTreePage {
                nodes: Vec::new(),
                next_page_token: None,
                history_available: false,
                cursor_expired: token.is_some(),
            });
        };
        let root_serial = record.root_serial;
        let anchor_serial = record.serial;
        let (horizon, after) = if let Some(token) = token {
            self.decode_cursor(tenant, anchor, anchor_serial, root_serial, token)?
        } else {
            (state.next_serial - 1, 0)
        };
        let maximum = if page_size == 0 { 32 } else { page_size };
        let mut nodes = Vec::new();
        let mut bytes = 1024_usize;
        let mut last = after;
        let mut more = false;
        for ((_, _, serial), id) in state.lineage_order.range(
            (tenant.clone(), root_serial, after.saturating_add(1))
                ..=(tenant.clone(), root_serial, horizon),
        ) {
            let record = state
                .records
                .get(id)
                .expect("lineage entry owns a retained record");
            // IDs are already bounded on admission; this protects embeddings
            // with a larger request limit without cloning an oversized atom.
            let node_bytes = 1024
                + id.0.len()
                + record.root.0.len()
                + record.parent.as_ref().map_or(0, |parent| parent.0.len())
                + record.target_service.0.len()
                + record
                    .caller_service
                    .as_ref()
                    .map_or(0, |service| service.0.len());
            if nodes.len() == maximum || bytes + node_bytes > MAXIMUM_TREE_BYTES {
                more = true;
                break;
            }
            if id.0.len() > MAXIMUM_ID_BYTES
                || record.target_service.0.len() > MAXIMUM_ID_BYTES
                || record
                    .caller_service
                    .as_ref()
                    .is_some_and(|service| service.0.len() > MAXIMUM_ID_BYTES)
                || record.root.0.len() > MAXIMUM_ID_BYTES
                || record
                    .parent
                    .as_ref()
                    .is_some_and(|id| id.0.len() > MAXIMUM_ID_BYTES)
            {
                return Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "activation-tree-identifier-limit",
                ));
            }
            let terminal_diagnostic = match &record.status.terminal_outcome {
                Some(RetainedActivationOutcome::PlatformFailure(failure)) => {
                    ActivationDiagnostic::from_error(failure)
                }
                _ => None,
            };
            nodes.push(ActivationTreeNode {
                activation_id: id.clone(),
                parent_activation_id: record.parent.clone(),
                root_activation_id: record.root.clone(),
                phase: record.status.phase,
                terminal_state: record.status.terminal_state,
                last_updated_unix_millis: record.status.last_updated_unix_millis,
                diagnostic_is_terminal: terminal_diagnostic.is_some(),
                diagnostic: terminal_diagnostic.or_else(|| record.observed_diagnostic.clone()),
                principal_kind: record.principal_kind,
                caller_service: record.caller_service.clone(),
                granted_budget: record.granted_budget.clone(),
                effective_deadline_unix_millis: record.effective_deadline_unix_millis,
                target_service: record.target_service.clone(),
                received_at_unix_millis: record.events[0].occurred_at_unix_millis,
            });
            bytes += node_bytes;
            last = *serial;
        }
        Ok(ActivationTreePage {
            nodes,
            history_available: true,
            cursor_expired: false,
            next_page_token: more
                .then(|| self.cursor(tenant, anchor, anchor_serial, root_serial, horizon, last)),
        })
    }

    /// Discover actual ingress roots through the same bounded retained index.
    /// At most 256 index entries are examined per call, even when a service has
    /// no matching roots. An empty page can carry a cursor to continue scanning.
    /// There is no additional service index, per-query owner or background task.
    // Keep scan accounting and cursor membership under the same observed lock.
    #[allow(clippy::too_many_lines)]
    pub fn inspect_roots(
        &self,
        tenant: &TenantId,
        service: &latent_core::ServiceId,
        from_unix_millis: Option<u64>,
        page_size: usize,
        token: Option<&str>,
    ) -> Result<ActivationTreePage, PlatformError> {
        if tenant.0.len() > MAXIMUM_ID_BYTES
            || service.0.len() > MAXIMUM_ID_BYTES
            || page_size > MAXIMUM_TREE_NODES
            || token.is_some_and(|token| token.len() > 160)
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-activation-roots-query",
            ));
        }
        self.validate_query(tenant, &ActivationId(service.0.clone()))?;
        let mut state = self.inner.lock();
        state.expire(
            self.inner.clock.monotonic_now(),
            self.inner.config.terminal_retention,
        );
        let tag = |horizon: u64, after_root: u64, after: u64| {
            let mut hash = Sha256::new();
            hash.update(b"latent.activation-roots.cursor.v1\0");
            hash.update(self.inner.cursor_epoch);
            for value in [&tenant.0, &service.0] {
                hash.update(value.len().to_le_bytes());
                hash.update(value.as_bytes());
            }
            hash.update([u8::from(from_unix_millis.is_some())]);
            for value in [from_unix_millis.unwrap_or(0), horizon, after_root, after] {
                hash.update(value.to_le_bytes());
            }
            hex_digest(&hash.finalize())
        };
        let invalid = || {
            error(
                PlatformErrorCode::InvalidArgument,
                "invalid-activation-roots-cursor",
            )
        };
        let (horizon, after_root, after) = if let Some(token) = token {
            if token.len() != 114 || !token.starts_with("r1") || !token.is_ascii() {
                return Err(invalid());
            }
            let horizon = u64::from_str_radix(&token[2..18], 16).map_err(|_| invalid())?;
            let root = u64::from_str_radix(&token[18..34], 16).map_err(|_| invalid())?;
            let after = u64::from_str_radix(&token[34..50], 16).map_err(|_| invalid())?;
            if root > horizon
                || after >= state.next_serial
                || (root == horizon && after >= horizon)
                || tag(horizon, root, after) != token[50..]
            {
                return Err(invalid());
            }
            (horizon, root, after)
        } else {
            (state.next_serial - 1, 0, 0)
        };
        if horizon == 0 {
            return Ok(ActivationTreePage {
                nodes: Vec::new(),
                next_page_token: None,
                history_available: true,
                cursor_expired: false,
            });
        }
        let maximum = if page_size == 0 { 32 } else { page_size };
        let mut nodes = Vec::new();
        let mut bytes = 1024_usize;
        let mut last = (after_root, after);
        let mut more = false;
        for (visited, ((_, root, serial), id)) in state
            .lineage_order
            .range(
                (tenant.clone(), after_root, after.saturating_add(1))
                    ..=(tenant.clone(), horizon, horizon),
            )
            .enumerate()
        {
            if visited == 256 || nodes.len() == maximum {
                more = true;
                break;
            }
            let record = state
                .records
                .get(id)
                .expect("lineage entry owns a retained record");
            if record.parent.is_some()
                || &record.target_service != service
                || *serial > horizon
                || from_unix_millis
                    .is_some_and(|from| record.events[0].occurred_at_unix_millis < from)
            {
                last = (*root, *serial);
                continue;
            }
            let node_bytes = 1024
                + id.0.len()
                + record.root.0.len()
                + record.target_service.0.len()
                + record
                    .caller_service
                    .as_ref()
                    .map_or(0, |value| value.0.len());
            if bytes + node_bytes > MAXIMUM_TREE_BYTES {
                more = true;
                break;
            }
            if id.0.len() > MAXIMUM_ID_BYTES
                || record.root.0.len() > MAXIMUM_ID_BYTES
                || record
                    .caller_service
                    .as_ref()
                    .is_some_and(|value| value.0.len() > MAXIMUM_ID_BYTES)
            {
                return Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "activation-tree-identifier-limit",
                ));
            }
            let terminal = match &record.status.terminal_outcome {
                Some(RetainedActivationOutcome::PlatformFailure(failure)) => {
                    ActivationDiagnostic::from_error(failure)
                }
                _ => None,
            };
            nodes.push(ActivationTreeNode {
                activation_id: id.clone(),
                parent_activation_id: None,
                root_activation_id: record.root.clone(),
                phase: record.status.phase,
                terminal_state: record.status.terminal_state,
                last_updated_unix_millis: record.status.last_updated_unix_millis,
                diagnostic_is_terminal: terminal.is_some(),
                diagnostic: terminal.or_else(|| record.observed_diagnostic.clone()),
                principal_kind: record.principal_kind,
                caller_service: record.caller_service.clone(),
                granted_budget: record.granted_budget.clone(),
                effective_deadline_unix_millis: record.effective_deadline_unix_millis,
                target_service: record.target_service.clone(),
                received_at_unix_millis: record.events[0].occurred_at_unix_millis,
            });
            bytes += node_bytes;
            last = (*root, *serial);
        }
        Ok(ActivationTreePage {
            nodes,
            history_available: true,
            cursor_expired: false,
            next_page_token: more.then(|| {
                format!(
                    "r1{horizon:016x}{:016x}{:016x}{}",
                    last.0,
                    last.1,
                    tag(horizon, last.0, last.1)
                )
            }),
        })
    }

    fn cursor_tag(
        &self,
        tenant: &TenantId,
        anchor: &ActivationId,
        anchor_serial: u64,
        root_serial: u64,
        horizon: u64,
        after: u64,
    ) -> String {
        let mut hash = Sha256::new();
        hash.update(b"latent.activation-tree.cursor.v1\0");
        hash.update(self.inner.cursor_epoch);
        for value in [&tenant.0, &anchor.0] {
            hash.update(value.len().to_le_bytes());
            hash.update(value.as_bytes());
        }
        for value in [anchor_serial, root_serial, horizon, after] {
            hash.update(value.to_le_bytes());
        }
        hex_digest(&hash.finalize())
    }
    fn cursor(
        &self,
        tenant: &TenantId,
        anchor: &ActivationId,
        anchor_serial: u64,
        root_serial: u64,
        horizon: u64,
        after: u64,
    ) -> String {
        format!(
            "a1{horizon:016x}{after:016x}{}",
            self.cursor_tag(tenant, anchor, anchor_serial, root_serial, horizon, after)
        )
    }
    fn decode_cursor(
        &self,
        tenant: &TenantId,
        anchor: &ActivationId,
        anchor_serial: u64,
        root_serial: u64,
        token: &str,
    ) -> Result<(u64, u64), PlatformError> {
        let invalid = || {
            error(
                PlatformErrorCode::InvalidArgument,
                "invalid-activation-tree-cursor",
            )
        };
        if token.len() != 98 || !token.starts_with("a1") || !token.is_ascii() {
            return Err(invalid());
        }
        let horizon = u64::from_str_radix(&token[2..18], 16).map_err(|_| invalid())?;
        let after = u64::from_str_radix(&token[18..34], 16).map_err(|_| invalid())?;
        if after >= horizon
            || self.cursor_tag(tenant, anchor, anchor_serial, root_serial, horizon, after)
                != token[34..]
        {
            return Err(invalid());
        }
        Ok((horizon, after))
    }
}
