public final class Main {
    public static void main(String[] args) {
        long value = new dev.latent.app.Capsule().run(0L);
        if (value != 42) throw new AssertionError(value);
        System.out.println(value);
    }
}
