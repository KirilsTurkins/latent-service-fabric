// Finite diagnostic, never a production socket module.
import * as streams from 'tests:typescript-import-borrow-gate/streams@1.0.0';
import { entered, intentionalTrap } from 'tests:typescript-import-borrow-gate/diagnostic@1.0.0';
import { read as originalRead } from 'latent:network/streams@0.1.0';
import { startRead } from 'lsf:typescript-borrow-probe';

function dispose(value: object): void {
    const symbol = (Symbol as unknown as {dispose?: symbol}).dispose || Symbol.for('dispose');
    const destroy = (value as Record<symbol, unknown>)[symbol];
    assertProbe(typeof destroy === 'function', 'generated-resource-destructor');
    destroy.call(value);
}
let calls = 0;
const yieldOnce = () => new Promise<void>(resolve => setTimeout(resolve, 1));
function assertProbe(condition: boolean, label: string): asserts condition {
    if (!condition) throw new Error('borrow-probe:' + label);
}
async function phase(value: number): Promise<void> {
    for (let attempt = 0; attempt < 128; ++attempt) {
        const actual = entered();
        if (actual === value) return;
        assertProbe(actual < value, 'phase-order');
        await yieldOnce();
    }
    throw new Error('borrow-probe:phase-bound');
}
async function send(connection: streams.Connection, bytes: Uint8Array): Promise<void> {
    assertProbe(await streams.write(connection, bytes, 1000) === bytes.length, 'short-write');
}
export const api = {
    async run(mode: number, port: number): Promise<string> {
        let diagnosticStage = 'entry';
        try {
            assertProbe(++calls === 1 && Number.isInteger(mode) && mode >= 0 && mode <= 3, 'one-shot-mode');
            diagnosticStage = 'connect-primary';
            const connection = await streams.connect({host: '127.0.0.1', port, transport: 'tcp', timeoutMillis: undefined});
            // Failure modes use a separately admitted real control connection so
            // host ownership samples precede the trap or original root deadline.
            diagnosticStage = 'connect-control-if-required';
            const control = mode === 1 || mode === 2 ? await streams.connect({
                host: '127.0.0.1', port, transport: 'tcp', timeoutMillis: undefined
            }) : undefined;
            // No application bytes are sent until the actual read-started witness.
            diagnosticStage = 'start-read';
            const operation = startRead(connection, 16, undefined);
            if (mode === 3) {
                diagnosticStage = 'normal-read-started';
                await phase(1);
                diagnosticStage = 'normal-write';
                await send(connection, new Uint8Array([110, 111, 114, 109])); // norm
                diagnosticStage = 'normal-read-result';
                const chunk = await operation.promise;
                assertProbe(chunk !== undefined, 'normal-chunk');
                let copy: Uint8Array;
                diagnosticStage = 'normal-copy-and-dispose';
                try { copy = (await streams.chunkBytes(chunk)).slice(); }
                finally { dispose(chunk); }
                diagnosticStage = 'normal-borrow-release';
                await operation.borrowReleased;
                assertProbe(copy.length === 1 && copy[0] === 112, 'copied-before-dispose');
                diagnosticStage = 'normal-consuming-close';
                assertProbe((await streams.close(connection)).state === 'closed', 'normal-close');
                return 'normal-read|copied|chunk-disposed|connection-consumed';
            }
            diagnosticStage = 'cancel-protocol';
            let logicalRejected = false, released = false;
            const logical = operation.promise.then(value => {
                if (value !== undefined) dispose(value);
                throw new Error('borrow-probe:unexpected-read-success');
            }, reason => {
                // Observe the actual public rejection. A finally/finish error must
                // fail this probe, never be normalized into a cancellation pass.
                assertProbe(reason === 'activation-runtime-import-cancelled', 'public-cancellation-reason');
                logicalRejected = true;
            });
            const acknowledgement = operation.borrowReleased.then(() => { released = true; });
            await phase(1);
            const cancellation = operation.cancel();
            // Attach both handlers immediately; neither receipt proves physical retirement.
            const cancelled = cancellation.then(() => {});
            await logical;
            await phase(2);
            assertProbe(logicalRejected && !released, 'logical-before-borrow-release');
            await send(connection, new Uint8Array([99, 97, 110, 99])); // canc
            // Same-connection peer confirms observing the logical-cancel handshake
            // by withholding release until this later write. Host samples owners here.
            for (let turn = 0; turn < 8; ++turn) {
                await yieldOnce();
                assertProbe(!released && entered() === 2, 'borrow-must-remain-held');
            }
            if (mode === 1 || mode === 2) {
                assertProbe(control !== undefined, 'separate-control-owner');
                const permit = await originalRead(control, 1, 1000);
                assertProbe(permit !== undefined, 'control-permit-chunk');
                let copy: Uint8Array;
                try { copy = (await streams.chunkBytes(permit)).slice(); }
                finally { dispose(permit); }
                assertProbe(copy.length === 1 && copy[0] === 116, 'control-permit-byte');
                assertProbe((await streams.close(control)).state === 'closed', 'control-consuming-close');
                assertProbe(!released && entered() === 2, 'primary-still-held-after-control');
                await send(connection, new Uint8Array([104, 101, 108, 100])); // held
                assertProbe(!released && entered() === 2, 'primary-held-at-terminal');
                if (mode === 1) {
                    try { throw new Error('borrow-probe:intentional-root-trap-with-held-read'); }
                    catch (reason) {
                        if (!(reason instanceof Error) || reason.message !== 'borrow-probe:intentional-root-trap-with-held-read') throw reason;
                        // The gate requires phase2 and emits a unique real Wasm trap.
                        // Other JS failures never reach this diagnostic operation.
                        intentionalTrap();
                        throw new Error('borrow-probe:intentional-trap-returned');
                    }
                }
                // Host deadline is shorter than this finite wait; never mark it pass here.
                for (let turn = 0; turn < 2048; ++turn) await yieldOnce();
                throw new Error('borrow-probe:missing-host-deadline');
            }
            await send(connection, new Uint8Array([114, 101, 108, 115])); // rels
            await acknowledgement;
            await cancelled;
            assertProbe(released && entered() === 3, 'actual-drop-before-ack');
            // A real ordinary read, distinct from the cancelled gate read, holds
            // this SAME original owner until the host samples it and sends permit.
            await send(connection, new Uint8Array([97, 99, 107, 33])); // ack!
            const permit = await originalRead(connection, 1, 1000);
            assertProbe(permit !== undefined, 'close-permit-chunk');
            let copy: Uint8Array;
            try { copy = (await streams.chunkBytes(permit)).slice(); }
            finally { dispose(permit); }
            assertProbe(copy.length === 1 && copy[0] === 99, 'close-permit-byte');
            const afterClose = await streams.close(connection);
            assertProbe(afterClose.state === 'closed', 'consuming-close');
            return 'logical-rejected|borrow-released|connection-consumed';
        } catch (reason) {
            // A diagnostic result must FAIL the unchanged exact host oracle.
            // No extra Promise, I/O, destructor, scheduler turn or authority.
            const text = reason instanceof Error ? reason.message :
                typeof reason === 'string' ? reason : '[non-string rejection]';
            const prefix = 'borrow-probe:diagnostic-failure:' + diagnosticStage + ':';
            return prefix + text.slice(0, 512 - prefix.length);
        }
    }
};
