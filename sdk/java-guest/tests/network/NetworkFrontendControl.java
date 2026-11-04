package dev.latent.guest.runtime.compiler;

import dev.latent.guest.runtime.HostCalls;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import org.teavm.backend.c.CTarget;
import org.teavm.backend.c.generate.CNameProvider;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.MethodReference;
import org.teavm.model.PreOptimizingClassHolderSource;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;
import org.teavm.vm.MemoryBuildTarget;
import org.teavm.vm.TeaVMBuilder;
import org.teavm.vm.TeaVMOptimizationLevel;

/** Fixed SDK callback C-frontend diagnostic; emitted text is not executed. */
public final class NetworkFrontendControl {
    private static final String HOST = "dev.latent.guest.runtime.HostCalls";
    private static void require(boolean value, String code) {
        if (!value) throw new AssertionError(code);
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 2 && (args[0].equals("original") || args[0].equals("corrected")),
                "network-frontend-arguments");
        ClassLoader loader = NetworkFrontendControl.class.getClassLoader();
        var mapping = DefaultSubstituteClassNameMapping.createWithPolicies(
                List.of(new ClasslibSubstitutionPolicy(), new RuntimeSubstitution()));
        var source = new PreOptimizingClassHolderSource(new ClasspathClassHolderSource(
                new ClasspathResourceProvider(loader), new ReferenceCache(), mapping));
        var names = new CNameProvider();
        var vm = new TeaVMBuilder(new CTarget(names)).setClassSource(source)
                .setClassLoader(loader).setStrict(true).build();
        var plugin = new RuntimePlugin();
        var classesField = RuntimePlugin.class.getDeclaredField("applicationClasses");
        classesField.setAccessible(true);
        @SuppressWarnings("unchecked") var classes = (Set<String>) classesField.get(plugin);
        require(classes.add(HOST), "network-frontend-selected-class");
        var transform = RuntimePlugin.class.getDeclaredMethod("transform", ClassHolder.class,
                ClassHolderTransformerContext.class);
        transform.setAccessible(true);
        int[] seen = {0};
        vm.add((cls, context) -> {
            if (!cls.getName().equals(HOST)) return;
            ++seen[0];
            try { transform.invoke(plugin, cls, context); }
            catch (ReflectiveOperationException failure) { throw new IllegalStateException(failure); }
        });
        vm.installPlugins();
        vm.setEntryPoint(App.class.getName());
        vm.setOptimizationLevel(TeaVMOptimizationLevel.FULL);
        var output = new MemoryBuildTarget();
        vm.build(output, "network-frontend");
        require(seen[0] == 1, "network-frontend-transform-count");
        require(vm.getProblemProvider().getSevereProblems().isEmpty(), "network-frontend-problems");
        var callback = new MethodReference(HOST, "suspendOwned", ValueType.INTEGER,
                ValueType.arrayOf(ValueType.BYTE), ValueType.INTEGER,
                ValueType.object(HOST + "$Call"), ValueType.object("org.teavm.interop.AsyncCallback"),
                ValueType.VOID);
        String symbol = names.forMethod(callback);
        Pattern definition = Pattern.compile("(?s)\\b" + Pattern.quote(symbol) + "\\s*\\([^;{}]*\\)\\s*\\{");
        String selected = null;
        long total = 0;
        require(output.getNames().size() <= 2048, "network-frontend-file-bound");
        for (String name : output.getNames()) {
            byte[] bytes = output.getContent(name);
            total += bytes.length;
            require(total <= 32L * 1024 * 1024, "network-frontend-byte-bound");
            if (!name.endsWith(".c")) continue;
            String text = new String(bytes, StandardCharsets.UTF_8);
            var match = definition.matcher(text);
            if (!match.find()) continue;
            require(selected == null && !match.find(), "network-frontend-one-callback-definition");
            match.reset(); require(match.find(), "network-frontend-callback-definition");
            int begin = match.start(), cursor = match.end(), depth = 1;
            // Generated fixed SDK method has no string or comment literals.
            while (cursor < text.length() && depth != 0) {
                char c = text.charAt(cursor++);
                if (c == '{') ++depth;
                if (c == '}') --depth;
            }
            require(depth == 0 && cursor - begin <= 65536, "network-frontend-callback-bound");
            selected = text.substring(begin, cursor);
        }
        require(selected != null && selected.contains("lsf_java_async_begin")
                && selected.contains("TEAVM_ARRAY_DATA"), "network-frontend-callback-emitted");
        Path target = Path.of(args[1]);
        Files.writeString(target, selected, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
        System.out.println("NETWORK_FRONTEND_CAPTURE " + args[0]
                + ";actual-sdk-callback;locked-ctarget;COMPONENT_QUALIFICATION=pending");
    }

    public static final class App {
        public static void main(String[] args) {
            HostCalls.Call call = HostCalls.admit();
            call.callOwned(1, new byte[] { 1, 2, 3 }, 3);
        }
    }
}
