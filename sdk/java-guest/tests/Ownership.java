package dev.latent.guest;

/** Local state-machine unit tests; actual component resource tests are separate. */
public final class Ownership {
    private static void require(boolean value) { if (!value) throw new AssertionError(); }
    private static void closed(Runnable operation) {
        try { operation.run(); throw new AssertionError("operation accepted a consumed owner"); }
        catch (IllegalStateException expected) { }
    }
    public static void main(String[] arguments) {
        int[] released = {0};
        Handle owner = new Handle(new Unsigned64(-1), value -> {
            require(value.bits() == -1); released[0]++;
        });
        Handle alias = owner;
        require(alias.borrow().bits() == -1);
        owner.close(); alias.close();
        require(released[0] == 1);
        closed(alias::borrow); closed(alias::consume);
        Handle consumed = new Handle(new Unsigned64(0), value -> released[0]++);
        require(consumed.consume().bits() == 0);
        consumed.close(); closed(consumed::borrow);
        require(released[0] == 1);
        Handle failing = new Handle(new Unsigned64(1), value -> {
            released[0]++; throw new IllegalArgumentException("uncertain external release");
        });
        try { failing.close(); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { }
        failing.close(); closed(failing::borrow);
        require(released[0] == 2); // Never retry an uncertain destructor.
        byte[] secret = {1, 2, 3};
        SensitiveBytes bytes = new SensitiveBytes(secret);
        require(bytes.borrow() == secret);
        bytes.close(); bytes.close();
        closed(bytes::borrow);
        require(java.util.Arrays.equals(secret, new byte[3]));
        require(Unsigned64.parse("18446744073709551615").bits() == -1);
        require(new Unsigned64(-1).toString().equals("18446744073709551615"));
        require(new Unsigned64(-1).compareTo(new Unsigned64(Long.MAX_VALUE)) > 0);
        System.out.println("Java ownership state machines passed; component gate remains required");
    }
}
