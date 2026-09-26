export const SEARCH_LIMITS = Object.freeze({bytes: 8 * 1024 * 1024, records: 6000, query: 128, results: 20});
export const searchOptions = Object.freeze({fields: ['title', 'heading', 'text'], storeFields: ['title', 'heading', 'route', 'version', 'profile', 'excerpt'],
  searchOptions: {boost: {title: 4, heading: 2}, prefix: true, fuzzy: 0.15, combineWith: 'AND'}});

export function searchState(search, channels) {
  const params = new URLSearchParams(search);
  const query = params.get('q') ?? '';
  const version = params.get('version') ?? 'development';
  return {query: query.slice(0, SEARCH_LIMITS.query), version,
    error: query.length > SEARCH_LIMITS.query ? 'The search query is too long.'
      : channels.includes(version) ? null : 'This documentation version is not published. Choose an available version.'};
}

export function channelFromPath(pathname, baseUrl, channels) {
  const prefix = `${baseUrl}docs/`;
  if (!pathname.startsWith(prefix)) return null;
  const segment = pathname.slice(prefix.length).split('/')[0];
  return channels.includes(segment) ? segment : 'development';
}

export function searchDocuments(index, query, version) {
  if (!query.trim() || query.length > SEARCH_LIMITS.query) return [];
  return index.search(query, {filter: result => result.version === version}).slice(0, SEARCH_LIMITS.results);
}
