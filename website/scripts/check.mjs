import {prepare} from '../lib/prepare.mjs';
import {loadPalette, validatePalette} from '../lib/palette.mjs';

const prepared = prepare({acceptance: process.argv.includes('--acceptance')});
console.log(JSON.stringify({palettePairings: validatePalette(loadPalette()).length}));
console.log(JSON.stringify({source: prepared.index.revision, dirty: prepared.manifest.dirty, pages: prepared.index.pages.length, assets: prepared.assets.length, coverage: prepared.manifest.coverage, excludedWikiPaths: prepared.manifest.excludedWikiPaths}));
