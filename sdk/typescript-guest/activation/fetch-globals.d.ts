// Explicit fetch candidate only. These declarations grant no provider authority
// and certify no browser environment. Unsupported runtime members fail closed.
type HeadersInit = Headers | Record<string, string> | Iterable<readonly [string, string]>;
declare class Headers implements Iterable<[string, string]> {
    constructor(init?: HeadersInit);
    append(name: string, value: string): void;
    delete(name: string): void;
    get(name: string): string | null;
    getSetCookie(): string[];
    has(name: string): boolean;
    set(name: string, value: string): void;
    entries(): IterableIterator<[string, string]>;
    keys(): IterableIterator<string>;
    values(): IterableIterator<string>;
    forEach(callback: (value: string, name: string, headers: Headers) => void, thisArg?: any): void;
    [Symbol.iterator](): IterableIterator<[string, string]>;
}
interface ReadableStreamReadResult<T> { done: boolean; value?: T; }
interface ReadableStreamDefaultReader<T> {
    read(): Promise<ReadableStreamReadResult<T>>;
    cancel(reason?: any): Promise<void>;
    releaseLock(): void;
    readonly closed: Promise<void>;
}
interface ReadableStream<T> {
    readonly locked: boolean;
    getReader(): ReadableStreamDefaultReader<T>;
    cancel(reason?: any): Promise<void>;
}
interface Body {
    readonly body: ReadableStream<Uint8Array> | null;
    readonly bodyUsed: boolean;
    arrayBuffer(): Promise<ArrayBuffer>;
    bytes(): Promise<Uint8Array>;
    text(): Promise<string>;
    json(): Promise<any>;
}
type BodyInit = string | ArrayBuffer | ArrayBufferView | URLSearchParams;
declare class URLSearchParams implements Iterable<[string, string]> {
    constructor(init?: string | URLSearchParams | Record<string, string> | Iterable<readonly [string, string]>);
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
    forEach(callback: (value: string, name: string, params: URLSearchParams) => void, thisArg?: any): void;
    [Symbol.iterator](): IterableIterator<[string, string]>;
}
declare class URL {
    constructor(input: string | URL, base?: string | URL);
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
interface RequestInit {
    method?: string;
    headers?: HeadersInit;
    body?: BodyInit | null;
    signal?: AbortSignal | null;
    redirect?: 'follow' | 'error' | 'manual';
    credentials?: 'omit' | 'same-origin' | 'include';
    cache?: 'default' | 'no-store' | 'reload' | 'no-cache' | 'force-cache' | 'only-if-cached';
    mode?: 'navigate' | 'same-origin' | 'no-cors' | 'cors';
    referrer?: string;
    referrerPolicy?: string;
    integrity?: string;
    keepalive?: boolean;
    duplex?: 'half';
}
declare class Request implements Body {
    constructor(input: string | Request, init?: RequestInit);
    readonly url: string;
    readonly method: string;
    readonly headers: Headers;
    readonly signal: AbortSignal;
    readonly redirect: 'follow' | 'error' | 'manual';
    readonly body: ReadableStream<Uint8Array> | null;
    readonly bodyUsed: boolean;
    arrayBuffer(): Promise<ArrayBuffer>;
    bytes(): Promise<Uint8Array>;
    text(): Promise<string>;
    json(): Promise<any>;
    clone(): Request;
}
interface ResponseInit { status?: number; statusText?: string; headers?: HeadersInit; }
declare class Response implements Body {
    constructor(body?: BodyInit | null, init?: ResponseInit);
    readonly status: number;
    readonly statusText: string;
    readonly ok: boolean;
    readonly headers: Headers;
    readonly url: string;
    readonly redirected: boolean;
    readonly type: string;
    readonly body: ReadableStream<Uint8Array> | null;
    readonly bodyUsed: boolean;
    arrayBuffer(): Promise<ArrayBuffer>;
    bytes(): Promise<Uint8Array>;
    text(): Promise<string>;
    json(): Promise<any>;
    clone(): Response;
    static error(): Response;
    static redirect(url: string, status?: number): Response;
    static json(value: any, init?: ResponseInit): Response;
}
declare function fetch(input: string | Request, init?: RequestInit): Promise<Response>;
