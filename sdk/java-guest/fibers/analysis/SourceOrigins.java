import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.util.JavacTask;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaFileObject;
import javax.tools.ToolProvider;

/** Trusted compiler-only source attribution; never loads application classes. */
public final class SourceOrigins {
    private static String quote(String text) {
        StringBuilder result = new StringBuilder("\"");
        for (int index = 0; index < text.length(); index++) {
            char value = text.charAt(index);
            if (value == '"' || value == '\\') result.append('\\').append(value);
            else if (value < 0x20) result.append(String.format(Locale.ROOT, "\\u%04x", (int)value));
            else result.append(value);
        }
        return result.append('"').toString();
    }

    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 1) throw new IllegalArgumentException("captured source root required");
        Path root = Path.of(arguments[0]).toRealPath();
        List<Path> sources;
        try (var paths = Files.walk(root)) {
            sources = paths.filter(path -> path.toString().endsWith(".java")).sorted().toList();
        }
        if (sources.isEmpty() || sources.size() > 1024) throw new IllegalArgumentException("source file limit");
        long bytes = 0;
        for (Path source : sources) {
            if (Files.isSymbolicLink(source) || !source.toRealPath().startsWith(root))
                throw new IllegalArgumentException("source escapes capture");
            bytes += Files.size(source);
            if (bytes > 16 * 1024 * 1024) throw new IllegalArgumentException("source byte limit");
        }
        var compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("pinned full JDK required");
        var diagnostics = new DiagnosticCollector<JavaFileObject>();
        try (var manager = compiler.getStandardFileManager(diagnostics, Locale.ROOT, StandardCharsets.UTF_8)) {
            var options = List.of("-proc:none", "--release", "25", "-encoding", "UTF-8", "-implicit:none");
            var task = (JavacTask)compiler.getTask(null, manager, diagnostics, options, null,
                manager.getJavaFileObjectsFromPaths(sources));
            // Parse only: symbol resolution is owned by the later captured
            // compilation, and no processor, initializer or application runs.
            var units = new ArrayList<CompilationUnitTree>();
            task.parse().forEach(units::add);
            if (diagnostics.getDiagnostics().stream().anyMatch(row -> row.getKind() == Diagnostic.Kind.ERROR))
                throw new IllegalArgumentException("javac source attribution failed");
            units.sort(Comparator.comparing(unit -> unit.getSourceFile().toUri().toString()));
            var identities = new HashSet<String>();
            var rows = new ArrayList<String>();
            for (var unit : units) {
                Path path = Path.of(unit.getSourceFile().toUri()).toRealPath();
                if (!path.startsWith(root)) throw new IllegalArgumentException("parsed source escapes capture");
                String packageName = unit.getPackageName() == null ? "" : unit.getPackageName().toString();
                String file = path.getFileName().toString();
                if (!identities.add(packageName + "/" + file))
                    throw new IllegalArgumentException("ambiguous package and SourceFile origin");
                rows.add("{\"source\":" + quote(root.relativize(path).toString().replace('\\', '/'))
                    + ",\"package\":" + quote(packageName) + "}");
            }
            System.out.println("{\"schemaVersion\":\"lsf.java.source-origins.v1\",\"sources\":["
                + String.join(",", rows) + "]}");
        }
    }
}
