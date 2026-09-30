package dev.latent.guest.server.net;
import java.io.Serializable;
/** A logical address value; no descriptor or permission to bind. */
public abstract class SocketAddress implements Serializable {
    protected SocketAddress() { }
}
