import {prepare} from '../lib/prepare.mjs';
import {readSource, repositoryRoot, requireValue} from '../lib/repository.mjs';

const languages = {'client-rust': 'Rust', 'client-typescript': 'TypeScript', 'client-go': 'Go', 'client-c': 'C', 'client-java': 'Java', 'client-dotnet': 'C#/.NET'};
// The original review matrix remains a review contract, not the catalogue's ceiling.
const integrationGuides = [
  ['development-changes', 'Choose workflows added since alpha.5', 'evaluate-install-contribute', ['capsule-author', 'operator', 'contributor'], [],
    ['start/development-changes']],
  ['application-libraries', 'Add, review and update application libraries', 'application-inputs', ['capsule-author'], Object.values(languages),
    ['how-to/add-application-libraries']],
  ...[['rust', 'Rust', 'rust-library-authoring'], ['c', 'C', 'c-dependencies'],
    ['typescript', 'TypeScript', 'typescript-library-authoring'], ['go', 'Go', 'go-library-authoring'],
    ['java', 'Java', 'java-dependencies'], ['dotnet', 'C#/.NET', 'dotnet-dependencies']]
    .map(([language, label, page]) => [`libraries-${language}`, `Capture ${label} application dependencies`, 'application-inputs',
      ['capsule-author'], [label], [`component-development/${page}`]]),
  ['packaged-resources', 'Capture immutable application resources', 'application-inputs', ['capsule-author'], Object.values(languages),
    ['component-development/packaged-resources']],
  ['java-processors', 'Approve Java source generators and annotation processors', 'application-inputs', ['capsule-author'], ['Java'],
    ['component-development/java-generators']],
  ['inspect-composition', 'Check composition, preparation and activation diagnostics', 'application-inputs', ['capsule-author', 'operator'], [],
    ['how-to/inspect-a-composition']],
  ['java-server', 'Compile ordinary Java HttpServer registrations', 'static-web-delivery', ['capsule-author', 'web-developer'], ['Java'],
    ['component-development/java-httpserver']],
  ['transactional-guest', 'Author a transactional aggregate guest', 'transactions-effects', ['capsule-author'], Object.values(languages),
    ['component-development/transactional-authoring']],
  ['transaction-recovery', 'Recover original commands and inspect deferred effects', 'transactions-effects', ['operator', 'client-developer'], Object.values(languages),
    ['operations/transaction-recovery']],
  ['deliver-website', 'Deliver an existing website', 'static-web-delivery', ['web-developer', 'operator'], [],
    ['how-to/deliver-a-website', 'how-to/serve-angular-and-docusaurus']],
  ['publish-static-build', 'Sign and publish a frontend build', 'static-web-delivery', ['web-developer', 'operator'], [],
    ['operations/static-release-workflow']],
  ['recover-static-routes', 'Update or roll back GET and HEAD routes', 'static-web-delivery', ['operator'], [],
    ['operations/static-route-sets']],
  ['static-site-api', 'Combine a static site and a TypeScript API', 'static-web-delivery', ['web-developer', 'capsule-author'], ['TypeScript'],
    ['how-to/static-site-and-api']],
  ['compress-static-assets', 'Serve smaller static downloads with gzip', 'static-web-delivery', ['web-developer', 'operator'], [],
    ['operations/static-compression']],
  ['publication-capacity', 'Plan publication storage and maintenance', 'static-web-delivery', ['operator'], [],
    ['operations/publication-retention']],
  ['container-node', 'Run a non-root Linux container node', 'container-operations', ['operator', 'evaluator'], [],
    ['operations/container-runtime']],
  ['container-backup', 'Back up and restore complete node state', 'container-operations', ['operator'], [],
    ['operations/local-storage-recovery']],
  ['local-https-edge', 'Configure an HTTPS edge for a local node', 'container-operations', ['operator'], [],
    ['operations/local-https-edge']],
  ['private-readiness', 'Check real node readiness over private HTTP', 'container-operations', ['operator'], [],
    ['operations/readiness-probes']],
  ['headless-publication', 'Publish sites from a private CI runner', 'container-operations', ['operator'], [],
    ['operations/headless-publication-ci']],
  ['container-handover', 'Replace a container with exclusive state ownership', 'container-operations', ['operator'], [],
    ['operations/container-handover']],
];
export default function discovery(_context, _options, prepared = prepare()) {
  const {index} = prepared;
  const coverage = JSON.parse(readSource(repositoryRoot, 'website/content/coverage.json').toString());
  const pageFor = (sourcePath, role) => {
    const source = index.pages.find(item => item.source === sourcePath);
    requireValue(source, `Guide catalogue page is not published: ${sourcePath}`);
    return {title: source.title, route: source.route, role};
  };
  const guides = coverage.rows.map(row => ({id: row.id, title: row.outcomes[0], topic: row.area, audience: row.audience,
    languages: row.id === 'author-capsule' ? Object.values(languages) : languages[row.id] ? [languages[row.id]] : [],
    pages: row.pages.map(page => pageFor(page.path, page.role))}));
  guides.push(...integrationGuides.map(([id, title, topic, audience, supportedLanguages, pages]) => ({
    id, title, topic, audience, languages: supportedLanguages, pages: pages.map(page => pageFor(`docs/${page}.md`, 'guide')),
  })));
  requireValue(new Set(guides.map(guide => guide.id)).size === guides.length, 'Duplicate guide catalogue task');
  return {name: 'lsf-discovery', async contentLoaded({actions}) { actions.setGlobalData({guides}); }};
}
