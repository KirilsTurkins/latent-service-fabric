import fs from 'node:fs';
import path from 'node:path';
import {requireValue, websiteRoot} from '../lib/repository.mjs';

export default function repositoryContent(_context, {manifest}) {
  return {
    name: 'lsf-repository-content',
    async postBuild({outDir}) {
      const relative = path.relative(path.join(websiteRoot, 'build'), outDir);
      requireValue(relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative), 'Build output must stay within website/build');
      for (const page of manifest.pages) {
        const output = path.join(outDir, ...decodeURIComponent(page.route).split('/').filter(Boolean), 'index.html');
        requireValue(fs.existsSync(output), `Expected published page was not built: ${page.source}`);
      }
      fs.writeFileSync(path.join(outDir, 'site-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
      console.log(`Built ${manifest.pages.length} source-backed pages and ${manifest.assets.length} approved assets (${manifest.channel}, dirty=${manifest.dirty}).`);
    },
  };
}
