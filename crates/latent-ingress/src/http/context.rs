use super::{HttpError, MAX_CONTEXT_BYTES};
use latent_activation::TraceContext;
use latent_core::{InvocationPrincipal, Metadata};

/// Authenticated native context, never deserialized from the HTTP/WIT payload.
/// The adapter passes these same values to the normal activation admission path;
/// guests read authority from latent:context/context@0.1.0.
pub struct TrustedContext {
    principal: InvocationPrincipal,
    trace: TraceContext,
}
impl TrustedContext {
    pub fn new(principal: InvocationPrincipal, trace: TraceContext) -> Result<Self, HttpError> {
        if principal.subject.is_empty() || trace.trace_id.0.is_empty() || trace.span_id.0.is_empty()
        {
            return Err(HttpError::InvalidContext);
        }
        let mut bytes = 0;
        for value in [
            Some(&principal.subject),
            principal.tenant.as_ref().map(|v| &v.0),
            principal.service.as_ref().map(|v| &v.0),
            Some(&trace.trace_id.0),
            Some(&trace.span_id.0),
        ]
        .into_iter()
        .flatten()
        {
            text(value, &mut bytes)?;
        }
        for fields in [&principal.claims, &trace.baggage] {
            metadata(fields, &mut bytes)?;
        }
        Ok(Self { principal, trace })
    }
    #[must_use]
    pub fn principal(&self) -> &InvocationPrincipal {
        &self.principal
    }
    #[must_use]
    pub fn trace(&self) -> &TraceContext {
        &self.trace
    }
}
fn text(value: &String, bytes: &mut usize) -> Result<(), HttpError> {
    if value.len() > 512 || value.chars().any(char::is_control) {
        return Err(HttpError::InvalidContext);
    }
    *bytes = bytes
        .checked_add(value.capacity())
        .ok_or(HttpError::InvalidContext)?;
    if *bytes > MAX_CONTEXT_BYTES {
        return Err(HttpError::InvalidContext);
    }
    Ok(())
}
fn metadata(fields: &Metadata, bytes: &mut usize) -> Result<(), HttpError> {
    if fields.len() > 32 {
        return Err(HttpError::InvalidContext);
    }
    for (key, value) in fields {
        *bytes = bytes.checked_add(96).ok_or(HttpError::InvalidContext)?;
        if key.is_empty() {
            return Err(HttpError::InvalidContext);
        }
        text(key, bytes)?;
        text(value, bytes)?;
    }
    Ok(())
}
