// The same standard parse/mutation vector runs in Node and the runtime guest.
export function urlReference(URLType, ParamsType) {
  const url = new URLType('../caf\u00e9?q=hello%20world&a=2&a=1#part', 'https://EXAMPLE.invalid:443/root/file');
  const params = url.searchParams;
  const identity = params === url.searchParams;
  params.append('snow', '\u2603');
  params.set('q', 'updated value');
  params.sort();
  const linked = [url.href, [...params], identity];
  url.search = '?x=7&x=8';
  const sameAfterURLMutation = params === url.searchParams;
  params.delete('x', '7');
  url.hash = '';
  const unchanged = [url.href, [...params]];
  url.hostname = 'invalid host';
  url.protocol = 'bad protocol';
  const invalidSetters = JSON.stringify([url.href, [...params]]) === JSON.stringify(unchanged);
  const standalone = new ParamsType([['b', '2'], ['a', '1'], ['a', '3']]);
  standalone.sort();
  return {linked, mutated: [url.href, [...params], sameAfterURLMutation],
    empty: new ParamsType().toString(), standalone: [standalone.toString(), standalone.has('a', '3'), standalone.getAll('a')], invalidSetters,
    invalid: (() => {try {new URLType('not a URL');return false;}catch {return true;}})()};
}

// The finite native profile deliberately refuses growth before either linked
// view changes. The actual runtime also checks physical retirement/reuse.
export function urlBoundedRejections(URLType, ParamsType) {
  const url = new URLType('https://example.invalid/base?a=1');
  const params = url.searchParams;
  const before = JSON.stringify([url.href, [...params]]);
  const refused = [];
  for (const change of [
    () => {url.href = 'https://example.invalid/' + 'a'.repeat(8193);},
    () => {url.search = '?' + 'a'.repeat(2731);},
    () => {url.search = '?' + Array(257).fill('x=1').join('&');},
    () => {params.append('x', 'a'.repeat(8193));},
    () => {params.set('x', 'a'.repeat(2731));},
    () => {new ParamsType(Array(257).fill(['x', '1']));},
  ]) {
    try {change(); refused.push(false);} catch {refused.push(true);}
    if (JSON.stringify([url.href, [...params]]) !== before || url.searchParams !== params)
      throw new Error('rejected URL mutation changed linked ownership');
  }
  params.append('accepted', 'fresh');
  return {refused, fresh: params.get('accepted'), identity: url.searchParams === params};
}
