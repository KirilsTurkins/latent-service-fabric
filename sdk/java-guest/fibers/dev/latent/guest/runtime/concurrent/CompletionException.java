package dev.latent.guest.runtime.concurrent;

/** Missing standard exception; preserve the original asynchronous cause. */
public class CompletionException extends RuntimeException {
    protected CompletionException() { }
    protected CompletionException(String message) { super(message); }
    public CompletionException(String message, Throwable cause) { super(message, cause); }
    public CompletionException(Throwable cause) { super(cause); }
}
