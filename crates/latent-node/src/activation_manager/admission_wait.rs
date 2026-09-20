use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_core::{ActivationClock, PlatformError, PlatformErrorCode};

use super::control::stage;
use super::transport_stop::TransportStop;
use crate::CancellationToken;

pub(super) struct Window<'a> {
    token: &'a CancellationToken,
    expiry: Option<Instant>,
    clock: &'a Arc<dyn ActivationClock>,
    transport: &'a TransportStop,
    until: tokio::time::Instant,
}

impl<'a> Window<'a> {
    pub(super) fn new(
        token: &'a CancellationToken,
        expiry: Option<Instant>,
        clock: &'a Arc<dyn ActivationClock>,
        transport: &'a TransportStop,
    ) -> Self {
        Self {
            token,
            expiry,
            clock,
            transport,
            until: tokio::time::Instant::now() + Duration::from_secs(5),
        }
    }

    pub(super) async fn check<T>(
        &self,
        mut operation: impl FnMut() -> Result<T, PlatformError>,
    ) -> Result<T, PlatformError> {
        loop {
            let failure = match operation() {
                Err(failure)
                    if failure.code == PlatformErrorCode::Unavailable
                        && (failure.message == "admission-authority-busy"
                            || failure.details.iter().any(|detail| {
                                detail.kind == "admission.limit"
                                    && detail.fields.get("scope").map(String::as_str)
                                        == Some("revision")
                                    && detail.fields.get("dimension").map(String::as_str)
                                        == Some("revision")
                                    && detail.fields.get("reason").map(String::as_str)
                                        == Some("admission-authority-busy")
                            })) =>
                {
                    failure
                }
                result => return result,
            };
            if tokio::time::Instant::now() >= self.until {
                return Err(failure);
            }
            stage(
                async {
                    tokio::time::sleep_until(
                        (tokio::time::Instant::now() + Duration::from_millis(10)).min(self.until),
                    )
                    .await;
                    Ok(())
                },
                self.token,
                self.expiry,
                self.clock,
                self.transport,
            )
            .await?;
            if tokio::time::Instant::now() >= self.until {
                return Err(failure);
            }
        }
    }
}
