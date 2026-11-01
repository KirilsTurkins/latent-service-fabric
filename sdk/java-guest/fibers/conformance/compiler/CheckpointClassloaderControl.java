package org.teavm.dependency;

import java.lang.reflect.InvocationTargetException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Path;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/** Real frontend with JCL absent from the compiler loader, as in Gradle. */
public final class CheckpointClassloaderControl {
    private static void require(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason);
    }

    public static void main(String[] arguments) throws Exception {
        require(arguments.length == 17, "checkpoint-classloader-fixed-input-count");
        String mode = arguments[0];
        require(mode.equals("original") || mode.equals("corrected"), "checkpoint-classloader-mode");
        List<URL> compilerInputs = new ArrayList<>();
        List<URL> applicationInputs = new ArrayList<>();
        for (int index = 1; index < arguments.length; ++index) {
            Path path = Path.of(arguments[index]).toRealPath();
            String name = path.getFileName().toString();
            boolean application = name.equals("teavm-classlib-0.15.0.jar")
                    || name.equals("teavm-platform-0.15.0.jar");
            (application ? applicationInputs : compilerInputs).add(path.toUri().toURL());
        }
        require(applicationInputs.size() == 2 && compilerInputs.size() == 14,
                "checkpoint-classloader-exact-partition");
        ClassLoader previous = Thread.currentThread().getContextClassLoader();
        try (var compiler = new URLClassLoader(compilerInputs.toArray(URL[]::new),
                     ClassLoader.getPlatformClassLoader());
             var application = new URLClassLoader(applicationInputs.toArray(URL[]::new), compiler)) {
            for (String name : new String[] { "org.teavm.classlib.impl.PlatformMarkerSupport",
                    "org.teavm.classlib.impl.ClasslibSubstitutionPolicy",
                    "org.teavm.classlib.impl.string.DefaultStringTransformer",
                    "org.teavm.classlib.java.lang.TObject" }) {
                boolean absent = false;
                try {
                    Class.forName(name, false, compiler);
                } catch (ClassNotFoundException expected) {
                    absent = true;
                }
                require(absent, "checkpoint-classloader-jcl-not-in-parent");
                require(Class.forName(name, false, application).getClassLoader() == application,
                        "checkpoint-classloader-jcl-owned-by-child");
            }
            require(Class.forName("org.teavm.model.util.AsyncMethodFinder", false, application)
                    .getClassLoader() == compiler, "checkpoint-classloader-finder-owned-by-parent");
            Thread.currentThread().setContextClassLoader(application);
            try {
                Class<?> fixture = Class.forName("org.teavm.dependency.CheckpointCompilerControl", true, compiler);
                fixture.getMethod("main", String[].class).invoke(null, (Object) new String[] { mode });
                checkClasslibIdentity(mode, fixture, compiler, applicationInputs);
            } catch (InvocationTargetException failure) {
                // Preserve the actual compiler failure, not a passing wrapper result.
                Throwable cause = failure.getCause();
                if (cause instanceof Error) throw (Error) cause;
                if (cause instanceof Exception) throw (Exception) cause;
                throw failure;
            }
        } finally {
            Thread.currentThread().setContextClassLoader(previous);
        }
        System.out.println("CHECKPOINT_CLASSLOADER_CONTROL PASS " + mode
                + ";isolated-jcl;unchanged-compiler-graph;classlib-archive-control");
    }
    private static void checkClasslibIdentity(String mode, Class<?> fixture, ClassLoader compiler,
            List<URL> originalInputs) throws Exception {
        Path folder = Files.createTempDirectory("checkpoint-classlib-control-");
        Path altered = folder.resolve("teavm-classlib-0.15.0.jar");
        try {
            List<URL> inputs = new ArrayList<>();
            for (URL input : originalInputs) {
                Path path = Path.of(input.toURI());
                if (path.getFileName().toString().equals(altered.getFileName().toString())) {
                    require(Files.size(path) == 17718996, "checkpoint-classlib-original-size");
                    byte[] bytes;
                    try (var source = Files.newInputStream(path)) {
                        bytes = source.readNBytes(17718997);
                    }
                    require(bytes.length == 17718996 && bytes[0] == 'P' && bytes[1] == 'K'
                            && bytes[2] == 3 && bytes[3] == 4, "checkpoint-classlib-zip-header");
                    // Change only a ZIP local-header timestamp: same length and
                    // identical class bodies, but no longer the locked archive.
                    bytes[10] ^= 1;
                    Files.write(altered, bytes);
                    inputs.add(altered.toUri().toURL());
                } else {
                    inputs.add(input);
                }
            }
            require(Files.isRegularFile(altered), "checkpoint-classlib-altered-input");
            try (var application = new URLClassLoader(inputs.toArray(URL[]::new), compiler)) {
                Thread.currentThread().setContextClassLoader(application);
                fixture.getMethod("checkClasslibIdentity", String.class).invoke(null, mode);
            }
        } finally {
            Files.deleteIfExists(altered);
            Files.deleteIfExists(folder);
        }
    }
}
