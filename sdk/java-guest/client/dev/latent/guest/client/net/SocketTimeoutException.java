package dev.latent.guest.client.net;

/** Standard timeout identity missing from the pinned TeaVM class library. */
public class SocketTimeoutException extends java.io.InterruptedIOException {
    private static final long serialVersionUID = -8846654841826352300L;

    public SocketTimeoutException() { }
    public SocketTimeoutException(String message) { super(message); }
}
