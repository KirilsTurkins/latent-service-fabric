import {prepare} from '../lib/prepare.mjs';
import {readSource, repositoryRoot} from '../lib/repository.mjs';

const languages = {'client-rust': 'Rust', 'client-typescript': 'TypeScript', 'client-go': 'Go', 'client-c': 'C', 'client-java': 'Java', 'client-dotnet': 'C#/.NET'};
export default function discovery() {
  const {index} = prepare();
  const coverage = JSON.parse(readSource(repositoryRoot, 'website/content/coverage.json').toString());
  const guides = coverage.rows.map(row => ({id: row.id, title: row.outcomes[0], topic: row.area, audience: row.audience,
    languages: languages[row.id] ? [languages[row.id]] : [], pages: row.pages.map(page => {
      const source = index.pages.find(item => item.source === page.path);
      return {title: source.title, route: source.route, role: page.role};
    })}));
  return {name: 'lsf-discovery', async contentLoaded({actions}) { actions.setGlobalData({guides}); }};
}
