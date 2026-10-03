package dev.latent.compiler;

import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.Tree;
import com.sun.source.util.JavacTask;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaFileObject;
import javax.tools.ToolProvider;

/** Parse source identities without attribution, processors or application startup. */
class SourceOwnership {
    private static final int MAX_SOURCES = 2048;
    private static final int MAX_DECLARATIONS = 8192;

    private record Input(Path root, String relative, boolean generated) { }

    private static void require(boolean condition, String code) {
        if (!condition) {
            throw new IllegalArgumentException(code);
        }
    }

    private static void declarations(ClassTree tree, String prefix, Set<String> owners) {
        String name = prefix + tree.getSimpleName();
        require(owners.add(name), "java-annotation-processor-source-owner-collision");
        require(owners.size() <= MAX_DECLARATIONS, "java-annotation-processor-source-owner-limit");
        for (Tree member : tree.getMembers()) {
            if (member instanceof ClassTree nested) {
                declarations(nested, name + "$", owners);
            }
        }
    }

    private static void verify(Path originalRoot, Path generatedRoot, Path manifest) throws Exception {
        List<String> lines = Files.readAllLines(manifest, StandardCharsets.UTF_8);
        require(!lines.isEmpty() && lines.size() <= MAX_SOURCES,
                "java-annotation-processor-source-count-limit");
        var inputs = new HashMap<Path, Input>();
        var files = new ArrayList<Path>();
        for (String line : lines) {
            String[] row = line.split("\t", -1);
            require(row.length == 2 && (row[0].equals("original") || row[0].equals("generated")),
                    "java-annotation-processor-source-owner-manifest-invalid");
            String name = row[1];
            require(!name.isEmpty() && name.length() <= 1024 && name.endsWith(".java")
                    && !name.startsWith("/") && !name.contains("\\")
                    && List.of(name.split("/", -1)).stream().noneMatch(
                            part -> part.isEmpty() || part.equals(".") || part.equals("..")),
                    "java-annotation-processor-source-owner-manifest-invalid");
            boolean generated = row[0].equals("generated");
            Path root = generated ? generatedRoot : originalRoot;
            Path file = root.resolve(name).normalize();
            require(file.startsWith(root) && !Files.isSymbolicLink(file) && Files.isRegularFile(file),
                    "java-annotation-processor-source-owner-input-invalid");
            require(inputs.put(file, new Input(root, name, generated)) == null,
                    "java-annotation-processor-source-owner-manifest-invalid");
            files.add(file);
        }
        var compiler = ToolProvider.getSystemJavaCompiler();
        require(compiler != null, "java-annotation-processor-source-parser-unavailable");
        var diagnostics = new DiagnosticCollector<JavaFileObject>();
        Set<String> original = new HashSet<>();
        Set<String> generated = new HashSet<>();
        Set<String> originalRoots = new HashSet<>();
        try (var manager = compiler.getStandardFileManager(diagnostics, null, StandardCharsets.UTF_8)) {
            // parse() performs no attribution, annotation processing or class loading.
            var task = (JavacTask) compiler.getTask(null, manager, diagnostics,
                    List.of("--release", "25", "-proc:none", "-encoding", "UTF-8",
                            "-classpath", "/nonexistent", "-sourcepath", "/nonexistent"),
                    null, manager.getJavaFileObjectsFromPaths(files));
            for (CompilationUnitTree unit : task.parse()) {
                Path file = Path.of(unit.getSourceFile().toUri()).toAbsolutePath().normalize();
                Input input = inputs.get(file);
                require(input != null && unit.getModule() == null,
                        "java-annotation-processor-source-owner-input-invalid");
                String pkg = unit.getPackageName() == null ? "" : unit.getPackageName().toString();
                String prefix = pkg.isEmpty() ? "" : pkg + ".";
                String basename = Path.of(input.relative()).getFileName().toString();
                if (input.generated()) {
                    String expected = (pkg.isEmpty() ? "" : pkg.replace('.', '/') + "/") + basename;
                    require(input.relative().equals(expected),
                            "java-annotation-processor-generated-source-package-path-mismatch");
                    require(!(pkg.equals("java") || pkg.startsWith("java.")
                            || pkg.equals("org.teavm.interop") || pkg.startsWith("org.teavm.interop.")
                            || pkg.equals("dev.latent.guest") || pkg.startsWith("dev.latent.guest.")
                            || pkg.equals("dev.latent.generated") || pkg.startsWith("dev.latent.generated.")),
                            "java-annotation-processor-generated-source-overrides-platform");
                }
                Set<String> owners = input.generated() ? generated : original;
                for (Tree type : unit.getTypeDecls()) {
                    if (type instanceof ClassTree declared) {
                        String owner = prefix + declared.getSimpleName();
                        if (!input.generated()) {
                            originalRoots.add(owner);
                        }
                        declarations(declared, prefix, owners);
                    }
                }
                if (basename.equals("package-info.java")) {
                    require(owners.add(prefix + "package-info"),
                            "java-annotation-processor-source-owner-collision");
                }
            }
        }
        require(diagnostics.getDiagnostics().stream().noneMatch(
                        diagnostic -> diagnostic.getKind() == Diagnostic.Kind.ERROR),
                "java-annotation-processor-generated-source-parse-failed");
        for (String owner : generated) {
            require(!original.contains(owner) && originalRoots.stream().noneMatch(
                            parent -> owner.startsWith(parent + "$")),
                    "java-annotation-processor-generated-source-owner-collision");
        }
    }

    public static void main(String[] args) {
        try {
            require(args.length == 3, "java-annotation-processor-source-owner-manifest-invalid");
            verify(Path.of(args[0]).toAbsolutePath().normalize(),
                    Path.of(args[1]).toAbsolutePath().normalize(), Path.of(args[2]));
            System.out.println("SOURCE-OWNERSHIP-OK");
        } catch (IllegalArgumentException error) {
            String reason = error.getMessage();
            System.err.println(reason != null && reason.startsWith("java-annotation-processor-")
                    ? reason : "java-annotation-processor-source-owner-control-failed");
            System.exit(1);
        } catch (Exception | LinkageError error) {
            System.err.println("java-annotation-processor-source-owner-control-failed");
            System.exit(1);
        }
    }
}
