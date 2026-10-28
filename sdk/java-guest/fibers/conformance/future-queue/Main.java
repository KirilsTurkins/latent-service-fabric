import dev.latent.app.Capsule;
public final class Main {
    public static void main(String[] args) {
        long[] expected = {41, 42, 42, 42};
        for (int mode = 0; mode < expected.length; mode++) {
            long value = new Capsule().run((long)mode);
            if (value != expected[mode]) throw new AssertionError("reference-future-queue");
            if (mode != 0) System.out.print(" ");
            System.out.print(value);
        }
        System.out.println();
    }
}
