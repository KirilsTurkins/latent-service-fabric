package dev.latent.guest.facilities.compiler;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import org.teavm.dependency.AbstractDependencyListener;
import org.teavm.dependency.DependencyAgent;
import org.teavm.model.MethodReference;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Observe the compiler's existing dependency graph. Never link a new method,
 * transform instructions or load/initialize an application class on the host.
 */
public final class ReachabilityPlugin implements TeaVMPlugin {
    @Override public void install(TeaVMHost host) {
        var queries = new ArrayList<Query>();
        try (var input = host.getClassLoader().getResourceAsStream(
                "META-INF/latent/compatibility-methods.tsv")) {
            if (input == null) return;
            var bytes = input.readNBytes(65537);
            if (bytes.length > 65536) return;
            if (bytes.length == 0) return;
            var ids = new HashSet<String>();
            for (String line : new String(bytes, StandardCharsets.UTF_8).split("\n")) {
                String[] fields = line.split("\t", -1);
                if (fields.length != 3 || !fields[0].matches("[a-f0-9]{64}")
                        || !ids.add(fields[0]) || queries.size() == 64) return;
                var reference = MethodReference.parseIfPossible(fields[1] + "." + fields[2]);
                if (reference == null) return;
                queries.add(new Query(fields[0], reference));
            }
        } catch (Exception error) { return; } // An unavailable observation cannot fail compilation.
        host.add(new AbstractDependencyListener() {
            private DependencyAgent completed;
            @Override public void completing(DependencyAgent agent) { completed = agent; }
            @Override public void complete() {
                if (completed == null) return; // Interrupted dependency traversal is unknown.
                var result = new StringBuilder("LSF_COMPILER_REACHABILITY_V1:complete;");
                for (int i = 0; i < queries.size(); i++) {
                    var query = queries.get(i);
                    var method = completed.getMethod(query.reference());
                    String state = method == null ? "not-retained"
                        : method.isMissing() ? "unknown" : "linked";
                    if (i > 0) result.append(',');
                    result.append(query.identity()).append('=').append(state);
                }
                System.out.println(result);
            }
        });
    }
    private record Query(String identity, MethodReference reference) { }
}
