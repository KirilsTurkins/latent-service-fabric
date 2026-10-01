package dev.latent.guest.runtime.concurrent;
public class TimeoutException extends Exception {
    public TimeoutException() { }
    public TimeoutException(String message) { super(message); }
}
