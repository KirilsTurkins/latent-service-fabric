public final class Main {
    public static void main(String[] arguments) {
        for (long mode = 0; mode < 4; mode++) {
            long result = new dev.latent.app.Capsule().run(mode);
            if (result != 42) throw new AssertionError("shutdown-now-reference-result");
        }
        System.out.println("42 42 42 42");
    }
}
