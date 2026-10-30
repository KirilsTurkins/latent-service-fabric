package dev.latent.guest.runtime.concurrent;

import java.util.concurrent.TimeUnit;

public interface Delayed extends Comparable<java.util.concurrent.Delayed> {
    long getDelay(TimeUnit unit);
}
