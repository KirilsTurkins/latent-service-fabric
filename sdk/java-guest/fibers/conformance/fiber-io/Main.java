public final class Main {
    public static void main(String[] args) throws Exception {
        try {
            for (long mode = 0; mode < 4; mode++) {
                if (new dev.latent.app.Capsule().run(mode) != 42) throw new AssertionError("reference-value");
                dev.latent.app.Capsule.referenceCleanup();
                if (mode == 2 && !dev.latent.app.Capsule.late) throw new AssertionError("reference-drain");
            }
            System.out.println("42 42 42 42");
        } finally { dev.latent.app.Capsule.referenceCleanup(); }
    }
}
