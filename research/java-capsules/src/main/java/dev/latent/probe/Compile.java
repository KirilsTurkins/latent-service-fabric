package dev.latent.probe;

import java.io.File;
import java.util.Arrays;
import java.util.regex.Pattern;
import org.teavm.tooling.TeaVMTargetType;
import org.teavm.tooling.TeaVMTool;
import org.teavm.vm.TeaVMOptimizationLevel;

/** Build-time JVM only. This class is not the application executed by LSF. */
public final class Compile {
    private Compile() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("Expected backend and output directory");
        }
        TeaVMTool tool = new TeaVMTool();
        tool.setTargetType(TeaVMTargetType.valueOf(args[0]));
        tool.setTargetDirectory(new File(args[1]));
        tool.setTargetFileName("probe.wasm");
        tool.setMainClass(Probe.class.getName());
        tool.setClassPath(Arrays.stream(System.getProperty("java.class.path")
                .split(Pattern.quote(File.pathSeparator))).map(File::new).toList());
        tool.setClassLoader(Compile.class.getClassLoader());
        tool.setOptimizationLevel(TeaVMOptimizationLevel.ADVANCED);
        tool.setIncremental(false);
        tool.setObfuscated(false);
        tool.setMinHeapSize(4 * 1024 * 1024);
        tool.setMaxHeapSize(16 * 1024 * 1024);
        tool.generate();
        if (tool.wasCancelled() || tool.getProblemProvider() == null
                || !tool.getProblemProvider().getSevereProblems().isEmpty()) {
            if (tool.getProblemProvider() != null) {
                tool.getProblemProvider().getProblems().forEach(System.err::println);
            }
            throw new IllegalStateException("TeaVM compilation did not complete");
        }
        System.out.println("TEAVM-GENERATED " + args[0]);
        System.out.println("REACHABLE-CLASSES " + tool.getClasses().size());
    }
}
