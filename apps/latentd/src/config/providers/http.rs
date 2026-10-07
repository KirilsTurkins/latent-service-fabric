use super::{invalid, token, HttpInstallation};
use latent_core::PlatformError;

impl HttpInstallation {
    pub(super) fn validate_installation(&self) -> Result<(), PlatformError> {
        self.identity.validate()?;
        self.configuration
            .validate()
            .map_err(|_| invalid("providers.http"))?;
        if self.credentials.capacity() > 8
            || self.credential_directory.is_some() == self.credentials.is_empty()
        {
            return Err(invalid("providers.http.credentials"));
        }
        for (index, credential) in self.credentials.iter().enumerate() {
            if !token(&credential.reference, 128)
                || !token(&credential.file, 128)
                || credential.file.contains(['/', '\\', ':'])
                || matches!(credential.file.as_str(), "." | "..")
                || !token(&credential.header, 64)
                || credential.destination >= self.configuration.destinations.len()
                || self.credentials[..index].iter().any(|previous| {
                    previous.reference == credential.reference
                        || previous.destination == credential.destination
                })
            {
                return Err(invalid("providers.http.credentials"));
            }
        }
        self.validate_deferred()
    }

    /// Closed endpoint approvals come only from the protected node configuration.
    /// The installed provider still owns the actual destination and credential.
    fn validate_deferred(&self) -> Result<(), PlatformError> {
        if self.deferred.is_empty() {
            return Ok(());
        }
        if self.deferred.capacity() > 16
            || self.credentials.len() != 1
            || self.credentials[0].destination != 0
            || !self.credentials[0]
                .header
                .eq_ignore_ascii_case("authorization")
            || self.credential_directory.is_none()
        {
            return Err(invalid("providers.http.deferred"));
        }
        for (index, endpoint) in self.deferred.iter().enumerate() {
            endpoint
                .validate(&self.configuration)
                .map_err(|_| invalid("providers.http.deferred"))?;
            if self.deferred[..index].iter().any(|previous| {
                previous.operation_path == endpoint.operation_path
                    || previous.lookup_prefix == endpoint.lookup_prefix
            }) {
                return Err(invalid("providers.http.deferred"));
            }
        }
        Ok(())
    }
}
