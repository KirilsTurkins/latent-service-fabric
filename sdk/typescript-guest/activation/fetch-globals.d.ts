// Candidate buffered API only; the compiler adds these declarations only with
// the exact async-import runtime and declared typed streaming HTTP capability.
type HeadersInit = Headers | Iterable<readonly [string, string]> | Record<string, string>;
type BodyInit = string | ArrayBuffer | ArrayBufferView;
interface RequestInit {
    method?: string;
    headers?: HeadersInit;
    body?: BodyInit | null;
    signal?: AbortSignal | null;
    redirect?: 'follow' | 'manual' | 'error';
    credentials?: 'omit' | 'same-origin';
    mode?: 'cors';
}
declare class Headers implements Iterable<[string, string]> {
    constructor(init?: HeadersInit);
    append(name: string, value: string): void;
    set(name: string, value: string): void;
    get(name: string): string | null;
    has(name: string): boolean;
    delete(name: string): void;
    entries(): IterableIterator<[string, string]>;
    keys(): IterableIterator<string>;
    values(): IterableIterator<string>;
    [Symbol.iterator](): IterableIterator<[string, string]>;
    forEach(callback: (value: string, name: string, parent: Headers) => void, thisArg?: unknown): void;
}
interface FetchBody {
    readonly bodyUsed: boolean;
    readonly body: null;
    arrayBuffer(): Promise<ArrayBuffer>;
    text(): Promise<string>;
    json(): Promise<any>;
}
declare class Request implements FetchBody {
    constructor(input: string | Request, init?: RequestInit);
    readonly url: string;
    readonly method: string;
    readonly headers: Headers;
    readonly signal: AbortSignal;
    readonly redirect: 'follow' | 'manual' | 'error';
    readonly credentials: 'omit' | 'same-origin';
    readonly mode: 'cors';
    readonly bodyUsed: boolean;
    readonly body: null;
    clone(): Request;
    arrayBuffer(): Promise<ArrayBuffer>;
    text(): Promise<string>;
    json(): Promise<any>;
}
interface ResponseInit { status?: number; statusText?: string; headers?: HeadersInit; }
declare class Response implements FetchBody {
    constructor(body?: BodyInit | null, init?: ResponseInit);
    readonly status: number;
    readonly statusText: string;
    readonly headers: Headers;
    readonly ok: boolean;
    readonly url: string;
    readonly redirected: boolean;
    readonly type: 'default' | 'basic';
    readonly bodyUsed: boolean;
    readonly body: null;
    clone(): Response;
    arrayBuffer(): Promise<ArrayBuffer>;
    text(): Promise<string>;
    json(): Promise<any>;
    static json(value: any, init?: ResponseInit): Response;
}
declare function fetch(input: string | Request, init?: RequestInit): Promise<Response>;
