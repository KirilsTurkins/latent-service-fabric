// Candidate declarations for the selected activation Promise engine only.
// These globals describe numeric timer handles; they do not declare a complete
// Node/browser environment or certify runtime API qualification.
declare function setTimeout(callback: (...arguments_: any[]) => void,
    delayMilliseconds?: number, ...arguments_: any[]): number;
declare function clearTimeout(id?: number): void;
declare function setInterval(callback: (...arguments_: any[]) => void,
    delayMilliseconds?: number, ...arguments_: any[]): number;
declare function clearInterval(id?: number): void;

interface AbortSignal {
    readonly aborted: boolean;
    readonly reason: any;
    onabort: ((event: any) => void) | null;
    throwIfAborted(): void;
    addEventListener(type: 'abort', listener: (event: any) => void,
        options?: boolean | { once?: boolean }): void;
    removeEventListener(type: 'abort', listener: (event: any) => void): void;
}
declare var AbortSignal: {
    abort(reason?: any): AbortSignal;
    timeout(milliseconds: number): AbortSignal;
    any(signals: Iterable<AbortSignal>): AbortSignal;
};
declare class AbortController {
    readonly signal: AbortSignal;
    abort(reason?: any): void;
}
