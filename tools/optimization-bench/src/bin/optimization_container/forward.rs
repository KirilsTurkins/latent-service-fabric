use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::{AsyncRead, AsyncWrite};
use tokio::net::TcpStream;

use super::Result;

pub(super) const CAPACITY: usize = 32;
pub(super) const BUFFER_BYTES: usize = 16 * 1024;

pub(super) async fn connection(mut client: TcpStream) -> Result<(u64, u64)> {
    client
        .set_nodelay(true)
        .map_err(|_| "forward-client-option")?;
    let mut app = tokio::time::timeout(
        Duration::from_secs(5),
        TcpStream::connect(super::command::CHILD_LISTEN),
    )
    .await
    .map_err(|_| "forward-connect-timeout")?
    .map_err(|_| "forward-connect")?;
    app.set_nodelay(true).map_err(|_| "forward-app-option")?;
    copy(&mut client, &mut app).await
}

async fn copy<A, B>(client: &mut A, app: &mut B) -> Result<(u64, u64)>
where
    A: AsyncRead + AsyncWrite + Unpin,
    B: AsyncRead + AsyncWrite + Unpin,
{
    tokio::io::copy_bidirectional_with_sizes(client, app, BUFFER_BYTES, BUFFER_BYTES)
        .await
        .map_err(|_| "forward-copy")
}

#[derive(Default)]
pub(super) struct Counts {
    pub accepted: u64,
    pub rejected: u64,
    pub completed: u64,
    pub failed: u64,
    pub joined: u64,
    pub aborted: u64,
    pub live: u64,
    pub maximum_live: u64,
    pub client_to_app_bytes: u64,
    pub app_to_client_bytes: u64,
}

impl Counts {
    pub fn accepted(&mut self) -> Result<()> {
        self.accepted = self
            .accepted
            .checked_add(1)
            .ok_or("forward-counter-overflow")?;
        self.live += 1;
        self.maximum_live = self.maximum_live.max(self.live);
        Ok(())
    }
    pub fn rejected(&mut self) -> Result<()> {
        self.rejected = self
            .rejected
            .checked_add(1)
            .ok_or("forward-counter-overflow")?;
        Ok(())
    }
    pub fn joined(
        &mut self,
        result: std::result::Result<Result<(u64, u64)>, tokio::task::JoinError>,
    ) -> Result<()> {
        self.joined = self
            .joined
            .checked_add(1)
            .ok_or("forward-counter-overflow")?;
        self.live = self
            .live
            .checked_sub(1)
            .ok_or("forward-counter-underflow")?;
        match result {
            Ok(Ok((up, down))) => {
                self.completed += 1;
                self.client_to_app_bytes = self
                    .client_to_app_bytes
                    .checked_add(up)
                    .ok_or("forward-counter-overflow")?;
                self.app_to_client_bytes = self
                    .app_to_client_bytes
                    .checked_add(down)
                    .ok_or("forward-counter-overflow")?;
                Ok(())
            }
            Err(error) if error.is_cancelled() => {
                self.aborted += 1;
                Err("forward-aborted")
            }
            _ => {
                self.failed += 1;
                Err("forward-failed")
            }
        }
    }
    pub fn value(&self) -> Value {
        json!({"capacity":CAPACITY,"buffer_bytes_per_direction":BUFFER_BYTES,
            "accepted":self.accepted.to_string(),"rejected":self.rejected.to_string(),
            "completed":self.completed.to_string(),"failed":self.failed.to_string(),
            "joined":self.joined.to_string(),"aborted":self.aborted.to_string(),
            "live":self.live.to_string(),"maximum_live":self.maximum_live.to_string(),
            "byte_count_scope":"completed-forward-tasks-only",
            "client_to_app_bytes":self.client_to_app_bytes.to_string(),"app_to_client_bytes":self.app_to_client_bytes.to_string()})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    #[tokio::test]
    async fn half_close_preserves_reverse_response_and_exact_bytes() {
        let (mut caller, mut forward_client) = tokio::io::duplex(64);
        let (mut forward_app, mut app) = tokio::io::duplex(64);
        let relay = tokio::spawn(async move { copy(&mut forward_client, &mut forward_app).await });
        let application = tokio::spawn(async move {
            let mut input = Vec::new();
            app.read_to_end(&mut input).await.unwrap();
            assert_eq!(input, b"opaque request");
            app.write_all(b"reverse response after EOF").await.unwrap();
            app.shutdown().await.unwrap();
        });
        caller.write_all(b"opaque request").await.unwrap();
        caller.shutdown().await.unwrap();
        let mut output = Vec::new();
        tokio::time::timeout(Duration::from_secs(2), caller.read_to_end(&mut output))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(output, b"reverse response after EOF");
        application.await.unwrap();
        assert_eq!(relay.await.unwrap().unwrap(), (14, 26));
    }

    #[tokio::test]
    async fn slow_receiver_backpressures_sender_without_unbounded_buffering() {
        let (mut caller, mut forward_client) = tokio::io::duplex(64);
        let (mut forward_app, mut app) = tokio::io::duplex(64);
        let relay = tokio::spawn(async move { copy(&mut forward_client, &mut forward_app).await });
        let mut sender = tokio::spawn(async move {
            caller
                .write_all(&vec![0x5a; BUFFER_BYTES * 8])
                .await
                .unwrap();
            caller.shutdown().await.unwrap();
            let mut result = Vec::new();
            caller.read_to_end(&mut result).await.unwrap();
        });
        assert!(
            tokio::time::timeout(Duration::from_millis(10), &mut sender)
                .await
                .is_err(),
            "bounded relay cannot absorb the entire payload while the receiver is idle"
        );
        let mut input = Vec::new();
        tokio::time::timeout(Duration::from_secs(2), app.read_to_end(&mut input))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(input, vec![0x5a; BUFFER_BYTES * 8]);
        app.shutdown().await.unwrap();
        sender.await.unwrap();
        assert_eq!(
            relay.await.unwrap().unwrap(),
            (u64::try_from(BUFFER_BYTES * 8).unwrap(), 0)
        );
    }
}
