import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import javax.tools.ToolProvider;

/** Compile only the captured, reviewed TeaVM class against checked original JARs. */
public final class Compile {
    public static void main(String[] args) throws Exception {
        if (args.length != 4) throw new IllegalArgumentException("coroutine-patch-arguments");
        Path source = Path.of(args[0]), control = Path.of(args[1]), output = Path.of(args[2]);
        Files.createDirectory(output);
        var compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("coroutine-patch-jdk-required");
        var options = new ArrayList<>(List.of("-proc:none", "--release", "11", "-g:none",
                "-encoding", "UTF-8", "-classpath", args[3], "-d", output.toString(),
                source.toString(), control.toString()));
        if (compiler.run(null, null, null, options.toArray(new String[0])) != 0) {
            throw new IllegalStateException("coroutine-patch-compile-failed");
        }
    }
}
