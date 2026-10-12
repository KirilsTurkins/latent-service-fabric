import java.io.PrintWriter;
import java.io.StringWriter;
import org.teavm.backend.c.generate.BufferedCodeWriter;
import org.teavm.model.util.VariableType;

/** Compiler emitter observation; no developer class initialization or guest execution. */
public final class CSpillDeclarations {
    public static void main(String[] args) {
        for (VariableType type : VariableType.values()) {
            BufferedCodeWriter writer = new BufferedCodeWriter(false);
            writer.indent().print("volatile ").printType(type).println(" teavm_spill_1;");
            writer.flush();
            StringWriter result = new StringWriter();
            writer.writeTo(new PrintWriter(result), "");
            System.out.print(type.name() + ":" + result.toString());
        }
    }
}
