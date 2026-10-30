// Compiler-owned, only staged for the exact bounded diagnostic source graph.
declare module 'lsf:typescript-borrow-probe' {
    import { read } from 'tests:typescript-import-borrow-gate/streams@1.0.0';
    export function startRead(...args: Parameters<typeof read>): Readonly<{
        promise: ReturnType<typeof read>;
        readonly borrowReleased: Promise<void>;
        cancel(): Promise<void>;
    }>;
}
