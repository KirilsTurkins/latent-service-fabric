package dev.latent.guest.runtime.compiler;
import java.lang.reflect.Method;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.common.LoopGraph;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ProgramUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Inspect the candidate class with the locked plugin and IR parser, not a guest run. */
public final class TimerClaimIrControl {
    static final String CLASS="dev.latent.guest.runtime.Activation";
    static final Set<String> HELPERS=Set.of("beginTimerStart","abandonUnstartedTimer","publishStartedTimer","beginWorkFinish","endWorkFinish");
    static void check(ClassHolder cls,String phase) {
        Set<String> found=new HashSet<>();int instructions=0;
        for(var method:cls.getMethods()) {
            if(!HELPERS.contains(method.getName()))continue;
            if(!found.add(method.getName()))throw new AssertionError("duplicate-helper");
            var program=method.getProgram();if(program==null)throw new AssertionError("missing-program");
            var graph=ProgramUtils.buildControlFlowGraph(program);var loops=new LoopGraph(graph);
            for(int i=0;i<loops.size();i++) {
                if(loops.loopAt(i)!=null)throw new AssertionError("loop:"+phase+":"+method.getName());
                if(loops.indexAt(i)>=0)for(int next:graph.outgoingEdges(i))
                    if(next==i)throw new AssertionError("self-loop:"+phase+":"+method.getName());
            }
            for(var block:program.getBasicBlocks())for(var instruction:block) {
                instructions++;
                if(instruction instanceof InvokeInstruction || instruction instanceof InitClassInstruction
                    || instruction instanceof MonitorEnterInstruction || instruction instanceof MonitorExitInstruction)
                    throw new AssertionError("split-kind:"+phase+":"+method.getName()+":"+instruction.getClass().getSimpleName());
            }
        }
        if(!found.equals(HELPERS))throw new AssertionError("missing-helpers:"+found);
        if(instructions==0)throw new AssertionError("empty-helpers:"+phase);
    }
    static int checkpoints(ClassHolder cls) {
        int count=0;
        for(var method:cls.getMethods())if(method.getName().equals("lookup"))
            for(var block:method.getProgram().getBasicBlocks())for(var instruction:block)
                if(instruction instanceof InvokeInstruction call && call.getMethod().equals(
                    new MethodReference(CLASS,"checkpoint",ValueType.VOID)))count++;
        return count;
    }
    @SuppressWarnings("unchecked") public static void main(String[] args)throws Exception {
        var source=new ClasspathClassHolderSource(new ClasspathResourceProvider(TimerClaimIrControl.class.getClassLoader()),
            new ReferenceCache(),DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var cls=source.get(CLASS);if(cls==null)throw new AssertionError("candidate-class-unavailable");check(cls,"parsed");
        if(checkpoints(cls)!=0)throw new AssertionError("unexpected-original-checkpoint");
        var plugin=new RuntimePlugin();var field=RuntimePlugin.class.getDeclaredField("applicationClasses");field.setAccessible(true);
        ((Set<String>)field.get(plugin)).add(CLASS);
        Method transform=RuntimePlugin.class.getDeclaredMethod("transform",ClassHolder.class,ClassHolderTransformerContext.class);
        transform.setAccessible(true);transform.invoke(plugin,cls,null);check(cls,"runtime-plugin-selected");
        if(checkpoints(cls)==0)throw new AssertionError("selected-loop-positive-control");
        System.out.println("TIMER_CLAIM_IR PASS selected-loop-positive;ownership-helpers-no-checkpoint-or-split-kind;not-guest");
    }
}
