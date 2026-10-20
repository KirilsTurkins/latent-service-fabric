package dev.latent.guest.facilities.compiler;

import java.util.List;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Actual locked compiler IR, never a native/guest execution substitute. */
public final class ClosedFilesystemModelControl {
    private static void require(boolean value, String label) {
        if (!value) throw new AssertionError(label);
    }
    private static boolean unsupported(MethodHolder method) {
        int raises = 0, creates = 0, initializers = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof RaiseInstruction) raises++;
            else if (instruction instanceof ConstructInstruction create
                    && create.getType().equals("java.lang.UnsupportedOperationException")) creates++;
            else if (instruction instanceof InvokeInstruction call
                    && call.getMethod().equals(new MethodReference("java.lang.UnsupportedOperationException",
                        "<init>", ValueType.VOID))) initializers++;
            else throw new AssertionError("unexpected-refusal-operation");
        }
        return raises == 1 && creates == 1 && initializers == 1;
    }
    public static void main(String[] args) {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(
            ClosedFilesystemModelControl.class.getClassLoader()), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var original = source.get("org.teavm.backend.c.runtime.fs.CFileSystem");
        var user = new MethodDescriptor("getUserDir", ValueType.object("java.lang.String"));
        var file = new MethodDescriptor("getFile", ValueType.object("java.lang.String"),
            ValueType.object("org.teavm.runtime.fs.VirtualFile"));
        var windows = new MethodDescriptor("isWindows", ValueType.BOOLEAN);
        require(original != null, "actual-locked-c-filesystem");
        require(original.getMethod(user).getProgram().basicBlockCount() > 1,
            "original-native-workdir-not-catchable-unsupported");
        var cls = ModelUtils.copyClass(original);
        var programs = cls.getMethods().stream().collect(java.util.stream.Collectors.toMap(
            MethodHolder::getDescriptor, method -> java.util.Optional.ofNullable(method.getProgram())));
        var originalPrograms = original.getMethods().stream().map(MethodHolder::getProgram).toList();
        var plugin = new ClosedFilesystemPlugin();
        require(args.length == 0 || (args.length == 1 && args[0].equals("--original")), "control-selection");
        if (args.length == 0) plugin.transformClass(cls, null);
        require(unsupported(cls.getMethod(user)) && unsupported(cls.getMethod(file)), "actual-refusal-bodies");
        var constant = cls.getMethod(windows).getProgram().basicBlockAt(0).getFirstInstruction();
        require(constant instanceof IntegerConstantInstruction value && value.getConstant() == 0,
            "closed-wasi-posix-path-metadata");
        int untouched = 0;
        for (var method : cls.getMethods()) if (!List.of(user, file, windows).contains(method.getDescriptor())) {
            require(java.util.Optional.ofNullable(method.getProgram()).equals(programs.get(method.getDescriptor())),
                "all-other-method-bodies-retained");
            untouched++;
        }
        require(untouched == 31 && original.getMethods().stream().map(MethodHolder::getProgram).toList()
            .equals(originalPrograms), "original-owner-and-31-other-methods");
        for (String name : List.of("java.io.File", "java.io.FileInputStream", "java.io.FileOutputStream",
                "java.lang.ClassLoader", "java.io.ByteArrayInputStream")) {
            var standard = source.get(name);
            require(standard != null, "actual-standard-or-resource-owner");
            var before = standard.getMethods().stream().map(MethodHolder::getProgram).toList();
            plugin.transformClass(standard, null);
            require(before.equals(standard.getMethods().stream().map(MethodHolder::getProgram).toList()),
                "standard-validation-and-resource-bodies-retained");
        }
        for (int mutation = 0; mutation < 5; mutation++) {
            var broken = ModelUtils.copyClass(original);
            if (mutation == 0) broken.setParent("outside.Owner");
            if (mutation == 1) broken.getInterfaces().clear();
            if (mutation == 2) broken.getField("cache").setType(ValueType.INTEGER);
            if (mutation == 3) broken.removeMethod(broken.getMethod(file));
            if (mutation == 4) {
                for (var block : broken.getMethod(windows).getProgram().getBasicBlocks())
                    for (var instruction : block) if (instruction instanceof InvokeInstruction call)
                        call.setMethod(new MethodReference("outside.Owner", "isWindows", ValueType.BOOLEAN));
            }
            var unchanged = broken.getMethod(user).getProgram();
            try { plugin.transformClass(broken, null); throw new AssertionError("unknown-layout-accepted"); }
            catch (IllegalStateException expected) { }
            require(broken.getMethod(user).getProgram() == unchanged, "refusal-before-partial-mutation");
        }
        try { plugin.transformClass(cls, null); throw new AssertionError("repeated-port-accepted"); }
        catch (IllegalStateException expected) { }
        var unrelated = new ClassHolder("outside.Owner");
        plugin.transformClass(unrelated, null);
        require(unrelated.getMethods().isEmpty(), "unseen-application-owner-retained");
        System.out.println("CLOSED_FILESYSTEM_MODEL PASS originals-native;unsupported=2;posix-target;other-bodies=31;validation-resources;layout=5;repeat;application-owner");
    }
}
