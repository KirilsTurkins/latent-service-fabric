package lsf.qualification;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import org.teavm.tooling.TeaVMTargetType;
import org.teavm.tooling.TeaVMTool;

/** Build-time compiler driver only. Never packaged or run by an LSF node. */
public final class CompileProbe {
    private CompileProbe() {}

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--targets")) {
            for (TeaVMTargetType target : TeaVMTargetType.values()) {
                System.out.println(target.name());
            }
            return;
        }
        if (args.length != 2) {
            throw new IllegalArgumentException("expected C|WEBASSEMBLY_GC OUTPUT");
        }
        TeaVMTargetType target = TeaVMTargetType.valueOf(args[0]);
        if (target != TeaVMTargetType.C && target != TeaVMTargetType.WEBASSEMBLY_GC) {
            throw new IllegalArgumentException("only maintained C and Wasm GC candidates are probed");
        }
        Path output = Path.of(args[1]);
        Files.createDirectory(output);
        TeaVMTool tool = new TeaVMTool();
        tool.setTargetType(target);
        tool.setMainClass(FeatureProbe.class.getName());
        tool.setClassLoader(CompileProbe.class.getClassLoader());
        tool.setTargetDirectory(output.toFile());
        tool.setTargetFileName(target == TeaVMTargetType.C ? "probe.c" : "probe.wasm");
        tool.setIncremental(false);
        tool.setObfuscated(false);
        tool.setMinHeapSize(4 * 1024 * 1024);
        tool.setMaxHeapSize(32 * 1024 * 1024);
        tool.generate();
        if (tool.wasCancelled() || tool.getProblemProvider() == null
                || !tool.getProblemProvider().getSevereProblems().isEmpty()) {
            if (tool.getProblemProvider() != null) {
                for (var problem : tool.getProblemProvider().getSevereProblems()) {
                    System.err.println(problem.getLocation() + ": " + problem.getText()
                            + " " + Arrays.toString(problem.getParams()));
                }
            }
            throw new IllegalStateException("TeaVM compilation did not complete");
        }
        System.out.println("compiled-java-source:" + target.name());
    }
}
