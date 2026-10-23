package dev.latent.app;

import dev.latent.guest.Result;
import java.lang.ref.WeakReference;
import org.apache.commons.lang3.concurrent.AtomicSafeInitializer;
import org.apache.commons.lang3.concurrent.ConcurrentException;

/** Two observed collections with each logical caller retaining ordinary Java roots. */
public final class Capsule {
    private static int invocation;
    private static final ThreadLocal<Cell> local = new ThreadLocal<>();
    private static volatile boolean childParked;
    private static volatile boolean rootCollected;
    private static volatile boolean readerReady;
    private static volatile boolean childCollected;
    private static volatile boolean aborted;
    private static volatile Throwable childFailure;
    // Observer objects are rooted independently of either victim continuation.
    // Weak referents remain owned only by the original caller locals/graphs.
    private static WeakReference<?>[] observers;
    private static int initializations;
    private static int rootPhase;
    private static volatile int childPhase;

    private static final class Cell {
        final int value;
        Cell(int value) { this.value = value; }
    }

    private static final class Held {
        final int[] numbers;
        final Object[] references;
        final Throwable error;
        final Cell token;
        Held(int[] numbers, Object[] references, Throwable error, Cell token) {
            this.numbers = numbers;
            this.references = references;
            this.error = error;
            this.token = token;
        }
    }

    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("checkpoint-gc-observable");
    }

    private static WeakReference<Object> discarded() {
        Object temporary = new Object();
        WeakReference<Object> witness = new WeakReference<>(temporary);
        require(witness.get() == temporary);
        return witness;
    }

    private static void collectOnce() {
        // The referent was really present in the completed helper frame. Any
        // automatic collection after that frame returned also occurs inside
        // this same parked-sibling phase. Never clear the witness manually.
        WeakReference<Object> witness = discarded();
        System.gc();
        require(witness.get() == null);
    }

    private static void retainedObservers(boolean rootVictim) {
        require(observers != null && observers.length == 10);
        int first = rootVictim ? 0 : 4;
        // Read only this phase's parked victim, and only AFTER collection.
        // No victim referent is transferred into the collector beforehand.
        for (int index = first; index < first + 4; index++) {
            WeakReference<?> observer = observers[index];
            require(observer != null && observer.get() != null);
        }
        WeakReference<?> tls = observers[rootVictim ? 8 : 9];
        require(tls != null && tls.get() != null);
    }

    public Result<String, String> greet(String mode) {
        try { return checked(mode); }
        catch (Throwable error) {
            // Fixed numeric phases only; an error never satisfies an ok case.
            return Result.err("checkpoint-gc-failure|root=" + rootPhase
                + "|child=" + childPhase + "|child-failed=" + (childFailure != null));
        }
    }

    private Result<String, String> checked(String mode) throws InterruptedException, ConcurrentException {
        rootPhase = 1;
        require(++invocation == 1 && !childParked && !rootCollected && !readerReady
            && !childCollected && !aborted && childFailure == null && observers == null && local.get() == null);
        if (mode.equals("fresh")) return Result.ok("checkpoint-gc|fresh=1");
        require(mode.equals("gc"));
        Object gate = new Object();
        int[] numbers = {19, 23};
        Cell token = new Cell(31);
        Object[] references = {token};
        Throwable retainedError;
        try { throw new IllegalArgumentException("root-gc-error"); }
        catch (IllegalArgumentException error) { retainedError = error; }
        WeakReference<int[]> numbersWitness = new WeakReference<>(numbers);
        WeakReference<Object[]> referencesWitness = new WeakReference<>(references);
        WeakReference<Throwable> errorWitness = new WeakReference<>(retainedError);
        WeakReference<Cell> tokenWitness = new WeakReference<>(token);
        local.set(new Cell(19));
        WeakReference<Cell> rootTlsWitness = new WeakReference<>(local.get());
        observers = new WeakReference<?>[] {numbersWitness, referencesWitness, errorWitness,
            tokenWitness, null, null, null, null, rootTlsWitness, null};

        AtomicSafeInitializer<Held> initializer = new AtomicSafeInitializer<>() {
            @Override protected Held initialize() {
                childPhase = 1;
                require(local.get() == null);
                local.set(new Cell(20));
                WeakReference<Cell> childTlsWitness = new WeakReference<>(local.get());
                initializations++;
                int[] childNumbers = {20, 22};
                Cell childToken = new Cell(32);
                Object[] childReferences = {childToken};
                Throwable childError;
                try { throw new IllegalArgumentException("child-gc-error"); }
                catch (IllegalArgumentException error) { childError = error; }
                WeakReference<int[]> childNumbersWitness = new WeakReference<>(childNumbers);
                WeakReference<Object[]> childReferencesWitness = new WeakReference<>(childReferences);
                WeakReference<Throwable> childErrorWitness = new WeakReference<>(childError);
                WeakReference<Cell> childTokenWitness = new WeakReference<>(childToken);
                observers[4] = childNumbersWitness;
                observers[5] = childReferencesWitness;
                observers[6] = childErrorWitness;
                observers[7] = childTokenWitness;
                observers[9] = childTlsWitness;
                try {
                    synchronized (gate) {
                        childPhase = 2;
                        childParked = true;
                        gate.notifyAll();
                        // Root cannot reacquire this monitor until wait has
                        // released it. All child locals remain live below.
                        while (!rootCollected && !aborted) gate.wait();
                    }
                    childPhase = 3;
                    require(!aborted);
                    require(childNumbersWitness.get() == childNumbers
                        && childReferencesWitness.get() == childReferences
                        && childErrorWitness.get() == childError
                        && childTokenWitness.get() == childToken);
                    require(childNumbers[0] + childNumbers[1] == 42
                        && childReferences[0] == childToken && childToken.value == 32
                        && childError instanceof IllegalArgumentException
                        && childError.getMessage().equals("child-gc-error")
                        && local.get() == childTlsWitness.get() && local.get().value == 20);
                    while (!readerReady && !aborted) { }
                    require(!aborted);
                    childPhase = 40;
                    // readerReady is set immediately before root enters the
                    // unchanged dependency get(), with no application yield.
                    // This caller runs when that contended dependency yields.
                    collectOnce();
                    childPhase = 41;
                    retainedObservers(true);
                    childCollected = true;
                    childPhase = 42;
                    require(childNumbersWitness.get() == childNumbers
                        && childReferencesWitness.get() == childReferences
                        && childErrorWitness.get() == childError
                        && childTokenWitness.get() == childToken
                        && local.get() == childTlsWitness.get() && local.get().value == 20);
                    childPhase = 5;
                    return new Held(childNumbers, childReferences, childError, childToken);
                } catch (Throwable original) {
                    // Commons publishes null as an initialized result (its
                    // sentinel is NO_INIT). Record failure before normal return
                    // so the other caller can leave get() and reject it below.
                    childFailure = original;
                    return null;
                }
            }
        };
        Thread child = new Thread(() -> {
            try {
                Held value = initializer.get();
                if (childFailure != null) {
                    synchronized (gate) { gate.notifyAll(); }
                    return;
                }
                require(value.numbers[0] + value.numbers[1] == 42
                    && value.references[0] == value.token && value.token.value == 32
                    && local.get().value == 20);
                childPhase = 6;
            } catch (Throwable error) {
                if (childFailure == null) childFailure = error;
                synchronized (gate) { gate.notifyAll(); }
            }
        });
        rootPhase = 2;
        child.start();
        try {
            synchronized (gate) {
                while (!childParked && childFailure == null) gate.wait();
                require(childFailure == null && childParked && !rootCollected && !childCollected);
                rootPhase = 30;
                collectOnce();
                rootPhase = 31;
                retainedObservers(false);
                rootPhase = 32;
                require(numbersWitness.get() == numbers && referencesWitness.get() == references
                    && errorWitness.get() == retainedError && tokenWitness.get() == token
                    && numbers[0] + numbers[1] == 42 && references[0] == token && token.value == 31
                    && local.get() == rootTlsWitness.get() && local.get().value == 19);
                rootCollected = true;
                gate.notifyAll();
            }
            rootPhase = 4;
            readerReady = true;
            Held value = initializer.get();
            rootPhase = 5;
            child.join();
            require(!child.isAlive() && childFailure == null && rootCollected && childCollected
                && initializations == 1 && value == initializer.get());
            rootPhase = 50;
            require(numbersWitness.get() == numbers && referencesWitness.get() == references
                && errorWitness.get() == retainedError && tokenWitness.get() == token
                && numbers[0] + numbers[1] == 42 && references[0] == token && token.value == 31
                && retainedError instanceof IllegalArgumentException
                && retainedError.getMessage().equals("root-gc-error")
                && local.get() == rootTlsWitness.get() && local.get().value == 19);
            rootPhase = 51;
            require(value.numbers[0] + value.numbers[1] == 42
                && value.references[0] == value.token && value.token.value == 32
                && value.error instanceof IllegalArgumentException
                && value.error.getMessage().equals("child-gc-error"));
            rootPhase = 6;
            return Result.ok("checkpoint-gc|collections=root:child|arrays=42:42|references=31:32"
                + "|errors=root:child|locals=19:20|initializations=1|fresh=1");
        } catch (Throwable original) {
            // A failed root assertion must not leave the already accepted child
            // waiting for a success flag that will never be set. Preserve the
            // original failure and both collection flags; this is not success.
            aborted = true;
            synchronized (gate) { gate.notifyAll(); }
            try { child.join(); }
            catch (Throwable cleanup) { original.addSuppressed(cleanup); }
            throw original;
        }
    }
}
