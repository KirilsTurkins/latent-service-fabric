use super::{
    config::{options, Configuration, MEDIA},
    control::terminal,
    require, Assertions, ClientProfile, Result, RpcClient,
};
use latent_sdk::management::{FailureCategory, InvokeResponse, OutcomeKnowledge};
use serde_json::Value;

fn guest(value: &InvokeResponse) -> Result<u64> {
    let value = value.success.as_ref().ok_or("guest-success-variant")?;
    require(
        value.payload.len() <= 128 && value.media_type == MEDIA,
        "guest-output-frame",
    )?;
    let result: Value = serde_json::from_slice(&value.payload).map_err(|_| "guest-output-json")?;
    let values = result
        .as_array()
        .filter(|values| values.len() == 1)
        .ok_or("guest-output-shape")?;
    values[0]
        .as_str()
        .and_then(|value| value.parse().ok())
        .ok_or("guest-output-u64")
}

pub async fn run(
    config: &Configuration,
    clients: &[RpcClient],
    assertions: &mut Assertions,
    activations: &mut Vec<String>,
) -> Result<()> {
    let client = &clients[0];
    // lsf-example-begin: invoke
    for (provider, expected, assertion) in [("http", 2201, "httpGuest"), ("blob", 4, "blobGuest")] {
        let response = client
            .invoke(config.request(provider, provider, None)?, options())
            .await
            .map_err(|_| {
                if provider == "http" {
                    "http-invocation-rpc"
                } else {
                    "blob-invocation-rpc"
                }
            })?;
        let actual = guest(&response.value)?;
        if actual != expected {
            return Err(match (provider, actual) {
                ("http", 10) => "http-guest-permission-denied",
                ("http", 11) => "http-guest-outcome-uncertain",
                ("http", _) => "http-guest-unexpected-result",
                _ => "blob-guest-unexpected-result",
            });
        }
        activations.push(format!("rust-{provider}"));
        assertions.insert(assertion, true);
    }
    // lsf-example-end: invoke
    let declared = client
        .invoke(
            config.request("callee", "declared", Some("fail"))?,
            options(),
        )
        .await
        .map_err(|_| "declared-invocation-rpc")?;
    require(
        declared.value.declared_error.is_some(),
        "declared-error-variant",
    )?;
    activations.push("rust-declared".into());
    assertions.insert("declaredError", true);
    let mut request = config.request("callee", "platform", Some("spin"))?;
    request.budget.as_mut().ok_or("budget-absent")?.cpu_fuel = 1000;
    let response = client
        .invoke(request, options())
        .await
        .map_err(|_| "platform-invocation-rpc")?;
    require(
        response.value.platform_failure.is_some(),
        "platform-failure-variant",
    )?;
    activations.push("rust-platform".into());
    assertions.insert("platformFailure", true);
    let mut request = config.request("http", "wrong-tenant", None)?;
    request.target.as_mut().ok_or("target-absent")?.tenant = "foreign".into();
    let failure = clients[2]
        .invoke(request, options())
        .await
        .err()
        .ok_or("tenant-not-denied")?;
    require(failure.grpc_status == Some(7), "wrong-tenant-status")?;
    assertions.insert("wrongTenant", true);
    let failure = clients[3]
        .invoke(config.request("http", "wrong-auth", None)?, options())
        .await
        .err()
        .ok_or("credential-not-denied")?;
    require(failure.grpc_status == Some(16), "wrong-credential-status")?;
    assertions.insert("wrongCredential", true);
    let failure = clients[4]
        .invoke(config.request("http", "limited", None)?, options())
        .await
        .err()
        .ok_or("response-limit-not-enforced")?;
    require(
        failure.dispatched
            && failure.outcome == OutcomeKnowledge::UNKNOWN
            && failure.category != FailureCategory::INVALID_REQUEST
            && failure.identity.activation_id.as_deref() == Some("rust-limited"),
        "response-limit-facts",
    )?;
    terminal(client, "rust-limited").await?;
    activations.push("rust-limited".into());
    assertions.insert("responseLimit", true);
    Ok(())
}
