import com.sun.source.tree.*;
import com.sun.source.util.JavacTask;
import com.sun.source.util.TreePath;
import com.sun.source.util.TreePathScanner;
import com.sun.source.util.Trees;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import javax.lang.model.element.*;
import javax.tools.*;

/** SDK-owned AST analysis. Application classes are parsed, never loaded/run. */
public final class ServerAnalyzer {
    private static final Object UNKNOWN = new Object();
    private static final String HTTP = "com.sun.net.httpserver.";
    private final Path root;
    private final Trees trees;
    private final Map<Element, TreePath> methods = new HashMap<>();
    private final Set<Element> active = new HashSet<>();
    private final List<Endpoint> endpoints = new ArrayList<>();
    private int visited;

    private static final class Failure extends RuntimeException {
        final String code;
        final TreePath at;
        Failure(String code, TreePath at) { this.code = code; this.at = at; }
    }
    private record Address(String address, int port) { }
    private static final class Endpoint {
        final Address address;
        final int backlog;
        final List<Context> contexts = new ArrayList<>();
        boolean started;
        Endpoint(Address address, int backlog) { this.address = address; this.backlog = backlog; }
    }
    private static final class Context {
        final String path;
        final TreePath at;
        String handler;
        Context(String path, String handler, TreePath at) { this.path = path; this.handler = handler; this.at = at; }
    }

    private ServerAnalyzer(Path root, Trees trees) { this.root = root; this.trees = trees; }
    private Failure fail(String code, TreePath at) { return new Failure(code, at); }
    private Element element(TreePath path) { return trees.getElement(path); }
    private TreePath child(TreePath parent, Tree tree) { return new TreePath(parent, tree); }
    private void tick(TreePath path) {
        if (++visited > 32768) throw fail("analysis-node-limit", path);
    }
    private static String owner(Element element) { return element.getEnclosingElement().toString(); }
    private static String quote(String value) {
        StringBuilder out = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            char c = value.charAt(index);
            if (c == '"' || c == '\\') out.append('\\').append(c);
            else if (c < 32) out.append(String.format(Locale.ROOT, "\\u%04x", (int)c));
            else out.append(c);
        }
        return out.append('"').toString();
    }
    private String location(TreePath at) {
        CompilationUnitTree unit = at.getCompilationUnit();
        Path file = Path.of(unit.getSourceFile().toUri()).normalize();
        if (!file.startsWith(root)) throw fail("source-location-outside-capture", at);
        long position = trees.getSourcePositions().getStartPosition(unit, at.getLeaf());
        return "{\"path\":" + quote("src/" + root.relativize(file).toString().replace('\\', '/'))
            + ",\"line\":" + unit.getLineMap().getLineNumber(position)
            + ",\"column\":" + unit.getLineMap().getColumnNumber(position) + "}";
    }
    private String handler(TreePath at) {
        long position = trees.getSourcePositions().getStartPosition(at.getCompilationUnit(), at.getLeaf());
        long line = at.getCompilationUnit().getLineMap().getLineNumber(position);
        long column = at.getCompilationUnit().getLineMap().getColumnNumber(position);
        TreePath parent = at;
        while (parent != null && !(parent.getLeaf() instanceof ClassTree)) parent = parent.getParentPath();
        Element type = parent == null ? null : element(parent);
        return (type == null ? "captured" : type.toString()) + ".handler@" + line + ":" + column;
    }

    private Object known(TreePath at, Map<Element, Object> values) {
        Element symbol = element(at);
        if (values.containsKey(symbol)) return values.get(symbol);
        if (symbol instanceof VariableElement variable && variable.getConstantValue() != null) {
            return variable.getConstantValue();
        }
        return UNKNOWN;
    }
    private int integer(Object value, int low, int high, TreePath at) {
        if (!(value instanceof Integer number) || number < low || number > high) {
            throw fail("constant-positive-logical-port-or-backlog-required", at);
        }
        return (Integer)value;
    }
    private String string(Object value, TreePath at) {
        if (!(value instanceof String text)) throw fail("constant-context-path-required", at);
        return (String)value;
    }
    private static boolean canonicalPath(String value) {
        return value.length() <= 1024 && value.matches("/[A-Za-z0-9._~!$&'()*+,;=:@/-]*")
            && !value.contains("//") && Arrays.stream(value.split("/", -1)).noneMatch(p -> p.equals(".") || p.equals(".."))
            && !value.equals("/_lsf") && !value.startsWith("/_lsf/");
    }
    private Object evaluate(TreePath at, Map<Element, Object> values) {
        tick(at);
        Tree tree = at.getLeaf();
        if (tree instanceof LiteralTree literal) return literal.getValue();
        if (tree instanceof IdentifierTree || tree instanceof MemberSelectTree) return known(at, values);
        if (tree instanceof ParenthesizedTree parentheses) return evaluate(child(at, parentheses.getExpression()), values);
        if (tree instanceof TypeCastTree cast) return evaluate(child(at, cast.getExpression()), values);
        if (tree instanceof AssignmentTree assignment) {
            Object value = evaluate(child(at, assignment.getExpression()), values);
            Element variable = element(child(at, assignment.getVariable()));
            if (variable != null && variable.getKind().isField() && (value instanceof Endpoint || value instanceof Context)) {
                throw fail("persistent-server-registration-field-unsupported", at);
            }
            values.put(variable, value);
            return value;
        }
        if (tree instanceof NewClassTree constructor) {
            Element symbol = element(at);
            List<Object> arguments = new ArrayList<>();
            for (ExpressionTree argument : constructor.getArguments()) arguments.add(evaluate(child(at, argument), values));
            if (symbol != null && owner(symbol).equals("java.net.InetSocketAddress")) {
                if (arguments.size() == 1) return new Address("wildcard", integer(arguments.get(0), 1, 65535, at));
                if (arguments.size() == 2) {
                    Object host = arguments.get(0);
                    String address = host == null || "0.0.0.0".equals(host) ? "wildcard"
                        : "127.0.0.1".equals(host) ? "loopback" : null;
                    if (address == null) throw fail("constant-wildcard-or-ipv4-loopback-required", at);
                    return new Address(address, integer(arguments.get(1), 1, 65535, at));
                }
                throw fail("unsupported-logical-address-constructor", at);
            }
            return UNKNOWN;
        }
        if (tree instanceof MethodInvocationTree invocation) {
            Element symbol = element(child(at, invocation.getMethodSelect()));
            if (!(symbol instanceof ExecutableElement method)) throw fail("unresolved-invocation", at);
            String api = owner(method), name = method.getSimpleName().toString();
            if (api.equals("java.net.ServerSocket") && name.equals("accept")) {
                throw fail("raw-accept-loop-has-no-finite-http-handler-boundary", at);
            }
            Object receiver = UNKNOWN;
            if (invocation.getMethodSelect() instanceof MemberSelectTree select) {
                receiver = evaluate(child(child(at, select), select.getExpression()), values);
            }
            List<Object> arguments = new ArrayList<>();
            for (ExpressionTree argument : invocation.getArguments()) arguments.add(evaluate(child(at, argument), values));
            if (api.equals(HTTP + "HttpServer")) {
                if (name.equals("create") && arguments.size() == 2 && arguments.get(0) instanceof Address address) {
                    if (!endpoints.isEmpty()) throw fail("simple-profile-requires-one-logical-endpoint", at);
                    Endpoint endpoint = new Endpoint(address, integer(arguments.get(1), 0, 65535, at));
                    endpoints.add(endpoint);
                    return endpoint;
                }
                if (!(receiver instanceof Endpoint endpoint)) throw fail("unresolvable-server-registration", at);
                if (name.equals("createContext")) {
                    if (endpoint.started) throw fail("live-context-mutation-unsupported", at);
                    if (arguments.size() < 1 || arguments.size() > 2) throw fail("unsupported-context-overload", at);
                    String path = string(arguments.get(0), at);
                    if (!canonicalPath(path)) throw fail("context-path-outside-canonical-profile", at);
                    if (endpoint.contexts.stream().anyMatch(row -> row.path.equals(path))) throw fail("conflicting-context-registration", at);
                    if (endpoint.contexts.size() >= 64) throw fail("context-limit", at);
                    Context context = new Context(path, arguments.size() == 2 ? handler(child(at, invocation.getArguments().get(1))) : null, at);
                    endpoint.contexts.add(context);
                    return context;
                }
                if (name.equals("start") && arguments.isEmpty()) {
                    if (endpoint.started || endpoint.contexts.isEmpty() || endpoint.contexts.stream().anyMatch(row -> row.handler == null)) {
                        throw fail("invalid-start-transition-or-missing-handler", at);
                    }
                    endpoint.started = true;
                    return UNKNOWN;
                }
                if (name.equals("setExecutor") && arguments.size() == 1 && arguments.get(0) == null && !endpoint.started) return UNKNOWN;
                throw fail("server-member-outside-simple-profile", at);
            }
            if (api.equals(HTTP + "HttpContext")) {
                if (name.equals("setHandler") && receiver instanceof Context context && context.handler == null && arguments.size() == 1
                        && endpoints.stream().noneMatch(endpoint -> endpoint.started && endpoint.contexts.contains(context))) {
                    context.handler = handler(child(at, invocation.getArguments().get(0)));
                    return UNKNOWN;
                }
                throw fail("context-member-outside-static-registration-profile", at);
            }
            if (methods.containsKey(method) && method.getModifiers().contains(Modifier.STATIC)) {
                return method(method, arguments, at);
            }
            if (api.startsWith(HTTP) || arguments.stream().anyMatch(value -> value instanceof Endpoint || value instanceof Context)) {
                throw fail("unresolved-binary-or-dynamic-server-helper", at);
            }
            return UNKNOWN;
        }
        // Handler bodies execute inside the real guest, never during analysis.
        if (tree instanceof LambdaExpressionTree || tree instanceof MemberReferenceTree) {
            inspectHandler(at);
            return UNKNOWN;
        }
        inspectOpaque(at);
        return UNKNOWN;
    }
    private boolean registrationMethod(Element symbol, Set<Element> checked) {
        if (!(symbol instanceof ExecutableElement method)) return false;
        if (owner(method).equals(HTTP + "HttpServer") || owner(method).equals(HTTP + "HttpContext")) return true;
        TreePath definition = methods.get(method);
        if (definition == null || !checked.add(method)) return false;
        boolean[] found = {false};
        new TreePathScanner<Void, Void>() {
            @Override public Void visitMethodInvocation(MethodInvocationTree tree, Void unused) {
                if (registrationMethod(element(child(getCurrentPath(), tree.getMethodSelect())), checked)) found[0] = true;
                return super.visitMethodInvocation(tree, unused);
            }
        }.scan(definition, null);
        return found[0];
    }
    private void inspectOpaque(TreePath at) {
        new TreePathScanner<Void, Void>() {
            @Override public Void visitMethodInvocation(MethodInvocationTree tree, Void unused) {
                tick(getCurrentPath());
                Element symbol = element(child(getCurrentPath(), tree.getMethodSelect()));
                if (symbol instanceof ExecutableElement method && owner(method).equals("java.net.ServerSocket")
                        && method.getSimpleName().contentEquals("accept")) {
                    throw fail("raw-accept-loop-has-no-finite-http-handler-boundary", getCurrentPath());
                }
                if (registrationMethod(symbol, new HashSet<>())) {
                    throw fail("dynamic-registration-control-flow-unsupported", getCurrentPath());
                }
                return super.visitMethodInvocation(tree, unused);
            }
        }.scan(at, null);
    }
    private void inspectHandler(TreePath at) {
        new TreePathScanner<Void, Void>() {
            @Override public Void visitMethodInvocation(MethodInvocationTree tree, Void unused) {
                tick(getCurrentPath());
                Element symbol = element(child(getCurrentPath(), tree.getMethodSelect()));
                if (symbol instanceof ExecutableElement method && owner(method).startsWith(HTTP)) {
                    String api = owner(method), name = method.getSimpleName().toString();
                    Set<String> exchange = Set.of("getRequestMethod", "getRequestURI", "getRequestHeaders", "getResponseHeaders",
                        "getRequestBody", "getResponseBody", "getHttpContext", "getResponseCode", "sendResponseHeaders", "close");
                    Set<String> headers = Set.of("getFirst", "add", "set", "put", "get", "containsKey", "remove", "clear",
                        "size", "isEmpty", "entrySet", "keySet", "values", "putAll");
                    if (!(api.equals(HTTP + "HttpExchange") && exchange.contains(name)
                            || api.equals(HTTP + "Headers") && headers.contains(name)
                            || api.equals(HTTP + "HttpContext") && Set.of("getPath", "getHandler").contains(name))) {
                        throw fail("handler-member-outside-simple-profile", getCurrentPath());
                    }
                }
                return super.visitMethodInvocation(tree, unused);
            }
        }.scan(at, null);
    }
    private Object statements(TreePath block, Map<Element, Object> values) {
        for (StatementTree statement : ((BlockTree)block.getLeaf()).getStatements()) {
            TreePath at = child(block, statement);
            if (statement instanceof VariableTree variable) {
                Object value = variable.getInitializer() == null ? UNKNOWN : evaluate(child(at, variable.getInitializer()), values);
                values.put(element(at), value);
            } else if (statement instanceof ExpressionStatementTree expression) {
                evaluate(child(at, expression.getExpression()), values);
            } else if (statement instanceof BlockTree) {
                Object returned = statements(at, values);
                if (returned instanceof Returned) return returned;
            } else if (statement instanceof ReturnTree result) {
                return new Returned(result.getExpression() == null ? UNKNOWN : evaluate(child(at, result.getExpression()), values));
            } else if (!(statement instanceof EmptyStatementTree)) inspectOpaque(at);
        }
        return UNKNOWN;
    }
    private record Returned(Object value) { }
    private Object method(ExecutableElement method, List<Object> arguments, TreePath call) {
        if (active.size() >= 16 || !active.add(method)) throw fail("recursive-registration-helper-unsupported", call);
        TreePath definition = methods.get(method);
        MethodTree tree = (MethodTree)definition.getLeaf();
        if (tree.getBody() == null || method.getParameters().size() != arguments.size()) throw fail("unresolved-source-helper", call);
        Map<Element, Object> values = new HashMap<>();
        for (int index = 0; index < arguments.size(); index++) values.put(method.getParameters().get(index), arguments.get(index));
        try {
            Object result = statements(child(definition, tree.getBody()), values);
            return result instanceof Returned returned ? returned.value() : UNKNOWN;
        } finally { active.remove(method); }
    }
    private String run(List<CompilationUnitTree> units, String entryPoint) {
        for (CompilationUnitTree unit : units) {
            new TreePathScanner<Void, Void>() {
                @Override public Void visitMethod(MethodTree tree, Void unused) {
                    Element symbol = element(getCurrentPath());
                    if (symbol != null) methods.put(symbol, getCurrentPath());
                    return super.visitMethod(tree, unused);
                }
            }.scan(unit, null);
        }
        List<ExecutableElement> entries = methods.keySet().stream().filter(symbol -> symbol instanceof ExecutableElement)
            .map(symbol -> (ExecutableElement)symbol).filter(symbol -> owner(symbol).equals(entryPoint)
                && symbol.getSimpleName().contentEquals("main") && symbol.getModifiers().containsAll(Set.of(Modifier.PUBLIC, Modifier.STATIC))
                && symbol.getReturnType().toString().equals("void") && symbol.getParameters().size() == 1
                && symbol.getParameters().get(0).asType().toString().equals("java.lang.String[]")).toList();
        if (entries.size() != 1) throw new Failure("exact-public-static-main-required", null);
        method(entries.get(0), List.of(UNKNOWN), methods.get(entries.get(0)));
        if (endpoints.size() != 1 || !endpoints.get(0).started) throw new Failure("one-finalized-server-registration-required", methods.get(entries.get(0)));
        Endpoint endpoint = endpoints.get(0);
        StringBuilder out = new StringBuilder("{\"initializer\":").append(quote(entryPoint + ".main"))
            .append(",\"extraction\":\"compiler-ast\",\"endpoints\":[{\"id\":\"server\",\"bind\":{\"address\":")
            .append(quote(endpoint.address.address())).append(",\"port\":").append(endpoint.address.port())
            .append(",\"backlog\":").append(endpoint.backlog).append("},\"contexts\":[");
        for (int index = 0; index < endpoint.contexts.size(); index++) {
            Context context = endpoint.contexts.get(index);
            if (index != 0) out.append(',');
            out.append("{\"path\":").append(quote(context.path)).append(",\"match\":\"literal-prefix\",\"handler\":")
                .append(quote(context.handler)).append(",\"source\":").append(location(context.at)).append('}');
        }
        return out.append("]}]}").toString();
    }

    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 3) throw new IllegalArgumentException("source root, entry point and captured classpath required");
        Path root = Path.of(arguments[0]).toRealPath();
        List<Path> sources;
        try (var paths = Files.walk(root)) { sources = paths.filter(path -> path.toString().endsWith(".java")).sorted().toList(); }
        long bytes = 0;
        if (sources.isEmpty() || sources.size() > 1024) throw new IllegalArgumentException("source file limit");
        for (Path source : sources) {
            if (Files.isSymbolicLink(source) || !source.toRealPath().startsWith(root)) throw new IllegalArgumentException("source escapes capture");
            bytes += Files.size(source);
            if (bytes > 16 * 1024 * 1024) throw new IllegalArgumentException("source byte limit");
        }
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("pinned full JDK required");
        DiagnosticCollector<JavaFileObject> diagnostics = new DiagnosticCollector<>();
        try (StandardJavaFileManager manager = compiler.getStandardFileManager(diagnostics, Locale.ROOT, StandardCharsets.UTF_8)) {
            List<String> options = List.of("-proc:none", "--release", "25", "-encoding", "UTF-8", "-classpath", arguments[2], "-implicit:none");
            JavacTask task = (JavacTask)compiler.getTask(null, manager, diagnostics, options, null,
                manager.getJavaFileObjectsFromPaths(sources));
            List<CompilationUnitTree> units = new ArrayList<>();
            task.parse().forEach(units::add);
            task.analyze();
            if (diagnostics.getDiagnostics().stream().anyMatch(row -> row.getKind() == Diagnostic.Kind.ERROR)) {
                System.out.println("{\"schemaVersion\":\"lsf.java.server.analysis.v1\",\"status\":\"blocked\",\"diagnostics\":[{\"code\":\"javac-source-attribution-failed\"}]}");
                System.exit(2);
            }
            ServerAnalyzer analyzer = new ServerAnalyzer(root, Trees.instance(task));
            try {
                String plan = analyzer.run(units, arguments[1]);
                System.out.println("{\"schemaVersion\":\"lsf.java.server.analysis.v1\",\"status\":\"observed\",\"plan\":" + plan + "}");
            } catch (Failure failure) {
                System.out.println("{\"schemaVersion\":\"lsf.java.server.analysis.v1\",\"status\":\"blocked\",\"diagnostics\":[{\"code\":"
                    + quote(failure.code) + (failure.at == null ? "" : ",\"source\":" + analyzer.location(failure.at)) + "}]}");
                System.exit(2);
            }
        }
    }
}
