use super::{require, Result};
use latent_core::TenantId;
use latent_protected_files::ProtectedFilePolicy;
use latent_sdk::{
    management::{CallOptions, InvocationTarget, InvokeRequest, ResourceBudget},
    network::{ClientConfig, ClientLimits, RpcClient},
};
use serde_json::{json, Value};
use std::{net::SocketAddr, path::Path, time::Duration};
use zeroize::Zeroizing;

pub const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";

pub struct Configuration {
    value: Value,
    endpoint: SocketAddr,
    credential: Zeroizing<String>,
}

pub fn field<'value>(value: &'value Value, name: &str) -> Result<&'value str> {
    value[name]
        .as_str()
        .filter(|value| !value.is_empty() && value.len() <= 4096)
        .ok_or("configuration-field")
}

pub fn options() -> CallOptions {
    CallOptions {
        timeout_millis: Some(5_000),
    }
}

impl Configuration {
    pub fn load() -> Result<Self> {
        require(
            cfg!(all(target_os = "linux", target_arch = "x86_64")),
            "protected-linux-profile",
        )?;
        let args: Vec<_> = std::env::args_os().skip(1).take(3).collect();
        require(
            args.len() == 2 && args[0] == "--config",
            "configuration-arguments",
        )?;
        let bytes = latent_protected_files::read(
            Path::new(&args[1]),
            16384,
            ProtectedFilePolicy::Integrity,
            "sdk.input",
        )
        .map_err(|_| "configuration-file")?;
        let value: Value = serde_json::from_slice(&bytes).map_err(|_| "configuration-json")?;
        require(
            value["schemaVersion"] == "latent.sdk.provider.workflow.input.v1"
                && value["language"] == "rust"
                && value["tenant"] == "tests",
            "configuration-profile",
        )?;
        let endpoint = field(&value, "endpoint")?
            .strip_prefix("http://")
            .ok_or("configuration-endpoint")?
            .parse()
            .map_err(|_| "configuration-endpoint")?;
        let bytes = Zeroizing::new(
            latent_protected_files::read(
                Path::new(field(&value, "credentialFile")?),
                256,
                ProtectedFilePolicy::Secret,
                "sdk.credential",
            )
            .map_err(|_| "protected-credential-file")?,
        );
        let credential = Zeroizing::new(
            std::str::from_utf8(&bytes)
                .map_err(|_| "credential-encoding")?
                .to_owned(),
        );
        Ok(Self {
            value,
            endpoint,
            credential,
        })
    }

    pub fn client(&self, tenant: &str, denied: bool, small: bool) -> Result<RpcClient> {
        let credential = if denied {
            Zeroizing::new("LSF-PUBLIC-WRONG-NODE-TOKEN-TEST-ONLY".into())
        } else {
            self.credential.clone()
        };
        RpcClient::new(ClientConfig {
            endpoint: self.endpoint,
            tenant: TenantId(tenant.into()),
            credential,
            limits: ClientLimits {
                maximum_calls: 4,
                maximum_response_bytes: if small { 64 } else { 65536 },
                rpc_timeout: Duration::from_secs(5),
                ..ClientLimits::default()
            },
        })
        .map_err(|_| "client-configuration")
    }

    pub fn field(&self, name: &str) -> Result<&str> {
        field(&self.value, name)
    }

    pub fn target(&self, name: &str) -> &Value {
        &self.value["targets"][name]
    }

    pub fn request(
        &self,
        provider: &str,
        suffix: &str,
        function: Option<&str>,
    ) -> Result<InvokeRequest> {
        let target = self.target(provider);
        let callee = provider == "callee";
        Ok(InvokeRequest {
            activation_id: Some(format!("rust-{suffix}")),
            target: Some(InvocationTarget {
                tenant: "tests".into(),
                service: field(target, "service")?.into(),
                route: Some(field(target, "route")?.into()),
                contract: field(target, "contract")?.into(),
                function: function.unwrap_or(field(target, "function")?).into(),
            }),
            payload: serde_json::to_vec(&if callee {
                json!([])
            } else {
                json!([0, self.field("upstreamUrl")?, "0"])
            })
            .map_err(|_| "request-payload")?,
            media_type: MEDIA.into(),
            budget: Some(ResourceBudget {
                cpu_fuel: if callee { 100_000_000 } else { 10_000_000_000 },
                memory_bytes: if callee { 4_194_304 } else { 16_777_216 },
                wall_time_limit_millis: Some(5_000),
                outbound_requests: if callee { 0 } else { 8 },
                blob_read_bytes: if provider == "blob" { 65_536 } else { 0 },
                blob_write_bytes: if provider == "blob" { 65_536 } else { 0 },
                ..Default::default()
            }),
            ..Default::default()
        })
    }
}
