"""Execute generated Java and the actual admission bridge; no component claim."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.java_capsule_project import ROOT
from tools.java_guest import java
from tools.java_guest.model import Graph


class AsyncAdmission(unittest.TestCase):
    @staticmethod
    def bindings():
        data = {
            'worlds': [{'name': 'service', 'package': 0,
                        'imports': {'pending': {'interface': {'id': 1}}},
                        'exports': {'api': {'interface': {'id': 0}}}}],
            'packages': [{'name': 'examples:sample@1.0.0'}],
            'interfaces': [
                {'name': 'api', 'package': 0, 'types': {}, 'functions': {
                    'run': {'name': 'run', 'kind': 'freestanding', 'params': [], 'result': None}}},
                {'name': 'pending', 'package': 0, 'types': {'item': 0}, 'functions': {
                    'finish': {'name': 'finish', 'kind': 'async-freestanding',
                               'params': [{'name': 'item', 'type': 1}], 'result': None},
                    'read': {'name': 'read', 'kind': 'async-freestanding',
                             'params': [{'name': 'item', 'type': 2}], 'result': None},
                    'validate': {'name': 'validate', 'kind': 'async-freestanding',
                                 'params': [{'name': 'text', 'type': 'string'}], 'result': None}}}],
            'types': [{'name': 'item', 'kind': 'resource', 'owner': {'interface': 1}},
                      {'name': None, 'kind': {'handle': {'own': 0}}, 'owner': None},
                      {'name': None, 'kind': {'handle': {'borrow': 0}}, 'owner': None}],
        }
        header = '''void exports_examples_sample_api_run(void);
extern probe_subtask_status_t examples_sample_pending_finish(sample_own_item_t item);
extern probe_subtask_status_t examples_sample_pending_read(sample_borrow_item_t item);
extern probe_subtask_status_t examples_sample_pending_validate(probe_string_t *text);
'''
        return java.generate(Graph(data, 'service', header, async_imports=True))

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'native JDK controls')
    def test_real_generated_calls_admit_before_own_or_borrow_and_retain_uncertain_wait(self):
        sdk = ROOT / 'sdk/java-guest'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = {
                'dev/latent/generated/Bindings.java': self.bindings(),
                # Only the original registry boundary is controlled. The actual
                # SDK HostCalls, Wire and Resource run unchanged on the JDK.
                'dev/latent/guest/runtime/Activation.java': '''package dev.latent.guest.runtime;
public final class Activation {
    public static boolean deny;
    public static int live, admitted, settled;
    public static Lease owner(Object kind) {
        if (deny) throw new IllegalStateException("activation-runtime-register-Wait-limit");
        live++; admitted++; return new Lease();
    }
    public static final class Lease implements AutoCloseable {
        private boolean closed;
        public void close() { if (!closed) { closed = true; live--; settled++; } }
    }
}''',
                'dev/latent/app/Capsule.java': '''package dev.latent.app;
public final class Capsule { public dev.latent.guest.Unit run() { return dev.latent.guest.Unit.VALUE; } }''',
                'org/teavm/runtime/Fiber.java': '''package org.teavm.runtime;
public final class Fiber { private static final Fiber current = new Fiber();
    public static Fiber current() { return current; } }''',
                'org/teavm/interop/Address.java': '''package org.teavm.interop;
public final class Address {
    public static int dataAddresses;
    public static Address ofData(byte[] bytes) { dataAddresses++; return new Address(); }
    public static Address fromInt(int value) { return new Address(); }
    public native int toInt(); public native Address add(int offset);
    public native byte getByte(); public native int getInt(); public native void putByte(byte value);
}''',
                'org/teavm/interop/Function.java': '''package org.teavm.interop;
public abstract class Function { public static native <T> T get(Class<T> type, Class<?> owner, String name); }''',
                'org/teavm/interop/AsyncCallback.java': '''package org.teavm.interop;
public interface AsyncCallback<T> { void complete(T value); }''',
                'org/teavm/interop/Async.java': 'package org.teavm.interop; public @interface Async {}',
                'org/teavm/interop/Import.java': 'package org.teavm.interop; public @interface Import { String name(); }',
                'org/teavm/interop/Export.java': 'package org.teavm.interop; public @interface Export { String name(); }',
                'dev/latent/guest/AdmissionControl.java': '''package dev.latent.guest;
import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import org.teavm.interop.Address;
public final class AdmissionControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("admission-order"); }
    private static Bindings.ExamplesSamplePendingItem item(int value) throws Exception {
        var constructor = Bindings.ExamplesSamplePendingItem.class.getDeclaredConstructor(int.class);
        constructor.setAccessible(true); return constructor.newInstance(value);
    }
    private static void denied(Runnable action) {
        try { action.run(); throw new AssertionError("denial-required"); }
        catch (IllegalStateException expected) {
            require(expected.getMessage().equals("activation-runtime-register-Wait-limit"));
        }
    }
    public static void main(String[] args) throws Exception {
        Activation.deny = true;
        var owned = item(7);
        denied(() -> Bindings.ExamplesSamplePending.finish(owned));
        Resource ownedResource = owned;
        require(ownedResource.borrow() == 7); ownedResource.releaseBorrow(); require(ownedResource.consume() == 7);
        var borrowed = item(9);
        denied(() -> Bindings.ExamplesSamplePending.read(borrowed));
        Resource borrowedResource = borrowed;
        require(borrowedResource.borrow() == 9); borrowedResource.releaseBorrow(); require(borrowedResource.consume() == 9);
        require(Activation.live == 0 && Activation.admitted == 0 && Address.dataAddresses == 0);

        Activation.deny = false;
        try { Bindings.ExamplesSamplePending.validate("\\uD800"); throw new AssertionError("invalid-text-required"); }
        catch (IllegalArgumentException expected) { }
        require(Activation.live == 0 && Activation.admitted == 1 && Activation.settled == 1);
        require(Address.dataAddresses == 0);

        var uncertain = item(11);
        // JDK cannot execute the native TeaVM suspension import. That failure
        // after entry exercises conservative retention, never a native result.
        try { Bindings.ExamplesSamplePending.finish(uncertain); throw new AssertionError("native-boundary-required"); }
        catch (UnsatisfiedLinkError expected) { }
        require(Activation.live == 1 && Activation.admitted == 2 && Activation.settled == 1);
        try { ((Resource)uncertain).consume(); throw new AssertionError("uncertain-transfer-must-stay-closed"); }
        catch (IllegalStateException expected) { }
        require(Address.dataAddresses == 1);
        System.out.println("JAVA_ASYNC_ADMISSION PASS own-denial;borrow-denial;wait-pre-entry-refund;uncertain-retained;COMPONENT_QUALIFICATION=pending");
    }
}''',
            }
            # The generated bridge normally receives this enum from the declared
            # activation WIT. Add only its declaration for this resource world.
            name = 'dev/latent/generated/Bindings.java'
            inputs[name] = inputs[name].replace('private Bindings() { }',
                'private Bindings() { } public enum LatentRuntimeActivationOwnerKind { Wait }')
            for name, text in inputs.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding='utf-8')
            sources = list(root.rglob('*.java')) + list((sdk / 'runtime/dev/latent/guest').glob('*.java'))
            sources.append(sdk / 'fibers/io/dev/latent/guest/runtime/HostCalls.java')
            compiled = subprocess.run(['javac', '-proc:none', '-encoding', 'UTF-8', '-d', str(root), *map(str, sources)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(['java', '-Xmx128m', '-cp', str(root), 'dev.latent.guest.AdmissionControl'],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('JAVA_ASYNC_ADMISSION PASS own-denial;borrow-denial;wait-pre-entry-refund;uncertain-retained;', result.stdout)
            print(result.stdout.rstrip())


if __name__ == '__main__':
    unittest.main()
