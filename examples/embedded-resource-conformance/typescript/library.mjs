import {read} from 'outside-embedded-resource-data';
let visits = 0;
export function resourceCase(mode) {
  if (++visits !== 1) throw new Error('resource-state-survived-retirement');
  return read(mode) + '|fresh=1';
}
