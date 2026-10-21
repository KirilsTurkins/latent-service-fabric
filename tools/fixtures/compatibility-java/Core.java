package outside.diagnosticsdata;

import java.io.FileInputStream;
import java.io.IOException;

/** Ordinary captured dependency. The host may compile/read it, never load it. */
public final class Core {
    private static int initializations;
    private static int constructors;
    private static int denials;
    static { initializations++; require(fallback() == 42); }

    public Core() { constructors++; require(fallback() == 42); }
    public static native int opaqueNative();
    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("diagnostics-original-library-state");
    }
    public static int fallback() {
        try (FileInputStream ignored = new FileInputStream("diagnostics-never-contact")) {
            throw new IllegalStateException("diagnostics-unexpected-filesystem-success");
        } catch (UnsupportedOperationException expected) {
            denials++;
            return 6 * 7; // Explicit pure application fallback, after refusal.
        } catch (IOException error) {
            throw new IllegalStateException("diagnostics-wrong-filesystem-error", error);
        }
    }
    public static void uncaught() {
        try (FileInputStream ignored = new FileInputStream("diagnostics-never-contact")) {
            throw new IllegalStateException("diagnostics-unexpected-filesystem-success");
        } catch (IOException error) {
            throw new IllegalStateException("diagnostics-wrong-filesystem-error", error);
        }
    }
    private static final class BadInitialization {
        static { uncaught(); }
        static int value() { return 0; }
    }
    public static void initializationFailure() { BadInitialization.value(); }
    public static String state(int expectedDenials) {
        require(initializations == 1 && constructors == 1 && denials == expectedDenials);
        return "init=1|ctor=1|denied=" + denials;
    }
}
