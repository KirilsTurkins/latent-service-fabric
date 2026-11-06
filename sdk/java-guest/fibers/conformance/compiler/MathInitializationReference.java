package dev.latent.guest.runtime.compiler;

import java.math.BigInteger;

/** Execute only the pinned JCL power-table arithmetic in the reference JVM.
 * This is neither a component nor a signed-node observation.
 */
public final class MathInitializationReference {
    private static void require(boolean value) {
        if (!value) throw new AssertionError("math-initializer-reference");
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 0);
        Class<?> multiplication = Class.forName("org.teavm.classlib.java.math.TMultiplication");
        Class<?> integer = Class.forName("org.teavm.classlib.java.math.TBigInteger");
        var value = integer.getMethod("valueOf", long.class);
        var text = integer.getMethod("toString");
        var step = multiplication.getDeclaredMethod("multiplyPAP", integer, integer);
        require(step.trySetAccessible());
        int checked = 0;
        for (String name : new String[] { "bigFivePows", "bigTenPows" }) {
            var field = multiplication.getDeclaredField(name);
            require(field.trySetAccessible());
            Object[] table = (Object[]) field.get(null);
            require(table.length == 32);
            int factor = name.equals("bigFivePows") ? 5 : 10;
            Object repeated = value.invoke(null, 1L);
            Object multiplier = value.invoke(null, (long) factor);
            for (int i = 0; i < table.length; ++i) {
                String expected = BigInteger.valueOf(factor).pow(i).toString();
                // Both the unmodified donor initializer and the iterative
                // recurrence must agree with an independent JDK implementation.
                require(text.invoke(table[i]).equals(expected));
                require(text.invoke(repeated).equals(expected));
                if (i + 1 < table.length) repeated = step.invoke(null, repeated, multiplier);
                ++checked;
            }
        }
        System.out.println("MATH_INITIALIZER_REFERENCE PASS " + checked);
    }

    private MathInitializationReference() { }
}
