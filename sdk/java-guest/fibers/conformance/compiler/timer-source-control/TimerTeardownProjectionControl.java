import java.io.File;
import java.lang.reflect.InvocationTargetException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Path;
import java.util.regex.Pattern;

/** Runs each private-ledger source projection in a fresh loader. */
public final class TimerTeardownProjectionControl {
    private static void run(URL[] urls, String name, String mode) throws Exception {
        try (var loader = new URLClassLoader(urls, ClassLoader.getPlatformClassLoader())) {
            var control = Class.forName(name, true, loader);
            try {
                control.getMethod("main", String[].class).invoke(null, (Object) new String[] {mode});
            } catch (InvocationTargetException error) {
                if (error.getCause() instanceof Exception exception) throw exception;
                if (error.getCause() instanceof Error failure) throw failure;
                throw error;
            }
        }
    }

    public static void main(String[] args) throws Exception {
        String[] entries = System.getProperty("java.class.path").split(Pattern.quote(File.pathSeparator));
        URL[] urls = new URL[entries.length];
        for (int i = 0; i < entries.length; i++) urls[i] = Path.of(entries[i]).toUri().toURL();
        for (String mode : new String[] {"race", "exceptional", "clean", "closed-before"}) {
            run(urls, "TimerTeardownRaceControl", mode);
        }
        run(urls, "TimerStopPrepublicationControl", "run");
        for (String mode : new String[] {"exceptional", "clean"}) {
            run(urls, "TimerAdmissionRaceControl", mode);
        }
        System.out.println("TIMER_TEARDOWN_PROJECTED PASS cases=7");
    }
}
