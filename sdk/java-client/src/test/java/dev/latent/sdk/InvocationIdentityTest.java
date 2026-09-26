package dev.latent.sdk;

public final class InvocationIdentityTest {
    private InvocationIdentityTest() { }

    public static void main(String[] args) throws Exception {
        ProfileVectors.run();
        ProfileLifetime.run();
        System.out.println("Java client profile semantic fixtures passed");
    }
}
