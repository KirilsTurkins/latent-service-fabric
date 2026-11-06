import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** Fixed two-level compiler/JCL loader diagnostic. */
public final class AmplifierSplitLauncher {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new AssertionError("split-inputs");
        String mode = args[0]; Path model = Path.of(args[1]).toRealPath();
        List<URL> compiler = new ArrayList<>(), application = new ArrayList<>();
        application.add(model.toUri().toURL());
        for (String value : args[2].split(java.util.regex.Pattern.quote(java.io.File.pathSeparator))) {
            Path path = Path.of(value).toRealPath();
            String name = path.getFileName().toString();
            boolean child = name.equals("teavm-classlib-0.15.0.jar") || name.equals("teavm-platform-0.15.0.jar");
            (child ? application : compiler).add(path.toUri().toURL());
        }
        if (application.size() != 3) throw new AssertionError("split-child-inputs");
        ClassLoader previous = Thread.currentThread().getContextClassLoader();
        try (var parent = new URLClassLoader(compiler.toArray(URL[]::new), ClassLoader.getPlatformClassLoader());
             var child = new URLClassLoader(application.toArray(URL[]::new), parent)) {
            if (Class.forName("org.teavm.model.util.AsyncMethodFinder", false, child).getClassLoader() != parent
                    || Class.forName("org.teavm.platform.plugin.PlatformPlugin", false, child).getClassLoader() != child
                    || Class.forName("org.teavm.classlib.impl.JCLPlugin", false, child).getClassLoader() != child) {
                throw new AssertionError("split-loader-identity");
            }
            Thread.currentThread().setContextClassLoader(child);
            try {
                Class<?> probe = Class.forName("org.teavm.platform.plugin.CheckpointAmplifierProbe", true, child);
                if (probe.getClassLoader() != child) throw new AssertionError("split-probe-loader");
                probe.getMethod("main", String[].class).invoke(null, (Object) new String[] { mode });
            } catch (java.lang.reflect.InvocationTargetException failure) {
                Throwable cause = failure.getCause();
                if (cause instanceof Exception) throw (Exception) cause;
                if (cause instanceof Error) throw (Error) cause;
                throw failure;
            }
        } finally {
            Thread.currentThread().setContextClassLoader(previous);
        }
        System.out.println("CHECKPOINT_AMPLIFIER_SPLIT PASS " + mode);
    }
}
