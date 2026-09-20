use super::abi::latent::{angular_renderer_internal::engine, http::client};
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Plan {
    url: String,
}

#[derive(Serialize)]
#[serde(tag = "outcome", rename_all = "kebab-case")]
pub enum Data {
    Response { status: u16, body: String },
    Failure { code: &'static str },
}

pub async fn load(input: &str) -> Option<Data> {
    let prepared = engine::prepare(input);
    assert!(prepared.len() <= 4096, "renderer-backend-plan-limit");
    let plan: Option<Plan> =
        serde_json::from_str(&prepared).expect("renderer-backend-plan-contract");
    let plan = plan?;
    assert!(
        !plan.url.is_empty() && plan.url.len() <= 2048 && !plan.url.chars().any(char::is_control),
        "renderer-backend-url-limit"
    );
    let request = client::Request {
        method: client::Method::Get,
        url: plan.url,
        headers: Vec::new(),
        body: None,
        body_media_type: None,
        idempotency_key: None,
        timeout_millis: Some(2000),
    };
    Some(match client::send(request).await {
        Ok(response) if response.body.len() <= 4096 => match String::from_utf8(response.body) {
            Ok(body) => Data::Response {
                status: response.status,
                body,
            },
            Err(_) => Data::Failure {
                code: "response-not-utf8",
            },
        },
        Ok(_) => Data::Failure {
            code: "response-too-large",
        },
        Err(error) => Data::Failure {
            code: category(error),
        },
    })
}

fn category(error: client::HttpError) -> &'static str {
    match error {
        client::HttpError::InvalidUrl => "invalid-url",
        client::HttpError::InvalidRequest => "invalid-request",
        client::HttpError::PermissionDenied => "permission-denied",
        client::HttpError::RequestTooLarge => "request-too-large",
        client::HttpError::ResponseTooLarge => "response-too-large",
        client::HttpError::DeadlineExceeded => "deadline-exceeded",
        client::HttpError::Cancelled => "cancelled",
        client::HttpError::BudgetExhausted => "budget-exhausted",
        client::HttpError::DnsFailed => "dns-failed",
        client::HttpError::TlsFailed => "tls-failed",
        client::HttpError::ConnectionFailed => "connection-failed",
        client::HttpError::Unavailable => "unavailable",
        client::HttpError::Uncertain => "uncertain",
    }
}
