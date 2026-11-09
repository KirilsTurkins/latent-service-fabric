import java.io.File;
import java.lang.reflect.InvocationTargetException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Path;
import java.util.regex.Pattern;
/** Runs each projected host-double case with a fresh activation and ledger. */
public final class TimerPostAckProjectionControl {
    public static void main(String[] args) throws Exception {
        String[] entries = System.getProperty("java.class.path").split(Pattern.quote(File.pathSeparator));
        URL[] urls = new URL[entries.length];
        for (int i = 0; i < entries.length; i++) urls[i] = Path.of(entries[i]).toUri().toURL();
        String[] modes = {"normal", "refused-start", "missing-token", "rollback-confirmed", "rollback-refused",
            "rollback-lost", "reentrant-root", "after-list", "fence-failure"};
        for (String mode : modes) {
            try (var loader = new URLClassLoader(urls, ClassLoader.getPlatformClassLoader())) {
                try { Class.forName("TimerPostAckControl", true, loader).getMethod("main", String[].class)
                    .invoke(null, (Object)new String[] {mode}); }
                catch (InvocationTargetException error) {
                    if (error.getCause() instanceof Exception exception) throw exception;
                    if (error.getCause() instanceof Error failure) throw failure;
                    throw error;
                }
            }
        }
        System.out.println("TIMER_POST_ACK_PROJECTED PASS cases=" + modes.length);
    }
}
