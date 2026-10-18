public final class Main {
    public static void main(String[] args) {
        for (long mode = 0; mode < 4; mode++)
            if (new dev.latent.app.Capsule().run(mode) != 42) throw new AssertionError("reference-value");
        System.out.println("42 42 42 42");
    }
}
