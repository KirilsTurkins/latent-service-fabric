use super::{driver::interruptible, NatsTriggers};
use crate::{
    network::{self, Auth, Connection, Dial, Scope},
    EventError, Result,
};
use latent_capabilities::broker::pools::{IngressRequest, PooledConnection};
use std::time::Instant;
use tokio::sync::watch;
pub(super) struct Open {
    pub connection: PooledConnection<Connection>,
    pub request: IngressRequest,
    pub auth: Auth,
}
impl NatsTriggers {
    pub(super) async fn open(
        &mut self,
        tenant: usize,
        index: usize,
        deadline: Instant,
        stop: &mut watch::Receiver<bool>,
    ) -> Result<Open> {
        let row = &mut self.tenants[tenant];
        if row.client.is_none() {
            row.client = Some(self.pools.client(
                &self.installed,
                u16::try_from(tenant).map_err(|_| EventError::InvalidEvent)?,
            )?);
        }
        let client = row.client.as_ref().expect("installed client").clone();
        let credential = &self.credentials[row.credential];
        let request = self.pools.ingress(
            &client,
            &self.config.bindings[index].tenant,
            deadline,
            3,
            65536 + 2 * self.config.maximum_payload_bytes,
        )?;
        let auth = network::current(credential)?;
        let scope = Scope::from(&request);
        let connection = interruptible(
            stop,
            network::connect_to(
                Dial {
                    pools: &self.pools,
                    endpoint: &self.config.endpoint,
                    tls: &self.tls,
                    attempts: &self.monitor.0.attempts,
                    reuses: &self.monitor.0.reuses,
                },
                &client,
                scope,
                &auth,
            ),
        )
        .await?;
        Ok(Open {
            connection,
            request,
            auth,
        })
    }
}
