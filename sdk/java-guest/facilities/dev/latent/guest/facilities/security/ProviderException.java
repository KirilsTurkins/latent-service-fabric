package dev.latent.guest.facilities.security;

/** Standard unchecked provider failure absent from the pinned class library. */
public class ProviderException extends RuntimeException {
    public ProviderException() { super(); }
    public ProviderException(String message) { super(message); }
    public ProviderException(String message, Throwable cause) { super(message, cause); }
    public ProviderException(Throwable cause) { super(cause); }
}
