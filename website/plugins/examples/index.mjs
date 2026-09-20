import {prepare} from '../../lib/prepare.mjs';
import {createRepositoryIndex} from '../../lib/repository.mjs';
import {prepareExamples} from './site.mjs';
import {validateExampleBuild} from './built.mjs';

export default function examplesPlugin(context) {
  const {examples} = prepare({baseUrl: context.siteConfig.baseUrl});
  function checkCurrentInputs() {
    const current = prepareExamples(createRepositoryIndex(), {persist: false});
    if (JSON.stringify(current.identity) !== JSON.stringify(examples.identity)) {
      throw new Error('Example inputs changed during the build; restart the website command to refresh its MDX cache identity');
    }
  }
  return {
    name: 'lsf-examples',
    loadContent() { checkCurrentInputs(); return examples.bundle; },
    contentLoaded({content, actions}) {
      // Only referenced region data. Never publish the registry, input inventory,
      // source bodies, evidence files or local absolute paths through global data.
      actions.setGlobalData(content);
    },
    postBuild({outDir}) {
      checkCurrentInputs();
      validateExampleBuild(outDir, createRepositoryIndex(), {examples: examples.identity});
    },
  };
}
