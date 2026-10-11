package dev.latent.guest.runtime.lang;

/** Standard exception absent from the pinned TeaVM class library. */
public class IllegalThreadStateException extends IllegalArgumentException {
    public IllegalThreadStateException() { super(); }
    public IllegalThreadStateException(String message) { super(message); }
}
