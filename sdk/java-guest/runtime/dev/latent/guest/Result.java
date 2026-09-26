package dev.latent.guest;

/** A declared WIT error is a value; arbitrary Java exceptions are never coerced. */
public final class Result<T, E> {
    private final boolean error;
    private final T value;
    private final E failure;
    private Result(boolean error, T value, E failure) {
        this.error = error; this.value = value; this.failure = failure;
    }
    public static <T, E> Result<T, E> ok(T value) {
        return new Result<>(false, java.util.Objects.requireNonNull(value), null);
    }
    public static <T, E> Result<T, E> err(E value) {
        return new Result<>(true, null, java.util.Objects.requireNonNull(value));
    }
    public boolean isError() { return error; }
    public T value() {
        if (error) throw new IllegalStateException("declared error has no success value");
        return value;
    }
    public E error() {
        if (!error) throw new IllegalStateException("success has no declared error");
        return failure;
    }
}
