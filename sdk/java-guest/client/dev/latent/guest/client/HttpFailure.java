package dev.latent.guest.client;

import java.io.IOException;

/** A closed provider outcome, including uncertainty; it conveys no retry right. */
public final class HttpFailure extends IOException {
    private final String code;
    public HttpFailure(String code) { super("latent-http:" + code); this.code = code; }
    public String code() { return code; }
    public boolean externalCompletionUncertain() { return code.equals("uncertain"); }
}
