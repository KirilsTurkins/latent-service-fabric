// Candidate buffered API only; the compiler adds these declarations only with
// the exact async-import runtime and declared typed streaming HTTP capability.
type HeadersInit = Headers | Iterable<readonly [string, string]> | Record<string, string>;

// Erased result types do not install Blob/FormData constructors or body support.
interface Blob { readonly size: number; readonly type: string; }
interface FormData { readonly [Symbol.toStringTag]: string; }
declare class URL {
    constructor(url: string | URL, base?: string | URL);
    href: string;
    protocol: string;
    username: string;
    password: string;
    host: string;
    hostname: string;
    port: string;
    pathname: string;
    search: string;
    hash: string;
    readonly origin: string;
    readonly searchParams: URLSearchParams;
    toString(): string;
    toJSON(): string;
}
declare class URLSearchParams implements Iterable<[string, string]> {
    constructor(init?: string | Iterable<readonly [string, string]> | Record<string, string>);
    readonly size: number;
    append(name: string, value: string): void;
    delete(name: string, value?: string): void;
    get(name: string): string | null;
    getAll(name: string): string[];
    has(name: string, value?: string): boolean;
    set(name: string, value: string): void;
    sort(): void;
    toString(): string;
    entries(): IterableIterator<[string, string]>;
    keys(): IterableIterator<string>;
    values(): IterableIterator<string>;
    [Symbol.iterator](): IterableIterator<[string, string]>;
    forEach(callback: (value: string, name: string, parent: URLSearchParams) => void, thisArg?: unknown): void;
}

type BodyInit = string | ArrayBuffer | ArrayBufferView | URLSearchParams;
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
    readonly body: FetchBodyStream | null;
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
    readonly body: FetchBodyStream | null;
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
    readonly type: 'default' | 'basic' | 'error';
    readonly bodyUsed: boolean;
    readonly body: FetchBodyStream | null;
    clone(): Response;
    arrayBuffer(): Promise<ArrayBuffer>;
    text(): Promise<string>;
    json(): Promise<any>;
    static json(value: any, init?: ResponseInit): Response;
    static error(): Response;
    static redirect(url: string | { toString(): string }, status?: number): Response;
}
declare function fetch(input: string | Request, init?: RequestInit): Promise<Response>;

interface FetchBodyReader {
    readonly closed: Promise<void>;
    read(): Promise<{done: false; value: Uint8Array} | {done: true; value: undefined}>;
    cancel(reason?: unknown): Promise<void>;
    releaseLock(): void;
}
interface FetchBodyStream {
    readonly locked: boolean;
    getReader(): FetchBodyReader;
    cancel(reason?: unknown): Promise<void>;
}
