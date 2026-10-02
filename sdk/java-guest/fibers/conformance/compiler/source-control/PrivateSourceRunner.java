public final class PrivateSourceRunner {
    public static void main(String[] args) throws Exception {
        try { CompletableFutureNativeControl.main(args); }
        finally { dev.latent.guest.runtime.Activation.cleanup(); }
        try { CompletableFutureOwnerControl.main(args); }
        finally { dev.latent.guest.runtime.Activation.cleanup(); }
    }
}
