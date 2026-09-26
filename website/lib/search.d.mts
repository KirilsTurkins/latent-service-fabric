export const SEARCH_LIMITS: {bytes: number; records: number; query: number; results: number};
export const searchOptions: import('minisearch').Options;
export function searchState(search: string, channels: string[]): {query: string; version: string; error: string | null};
export function channelFromPath(pathname: string, baseUrl: string, channels: string[]): string | null;
export function searchDocuments(index: import('minisearch').default, query: string, version: string): import('minisearch').SearchResult[];
