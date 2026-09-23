package dev.latent.guest;
public final class Option<T> {
    private final T value;
    private Option(T value) { this.value = value; }
    public static <T> Option<T> none() { return new Option<>(null); }
    public static <T> Option<T> some(T value) { return new Option<>(java.util.Objects.requireNonNull(value)); }
    public boolean isSome() { return value != null; }
    public T value() {
        if (value == null) throw new IllegalStateException("absent option");
        return value;
    }
}
