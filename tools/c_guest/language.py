"""Captured C language modes; no free-form compiler flags or new authority."""
DEFAULT = 'c11'
SUPPORTED = frozenset((DEFAULT, 'c23'))
RECIPE = ('tools/c_guest/language.py',)


def selected_standard(project, graph=None):
    standard = project.get('languageStandard', DEFAULT)
    if type(standard) is not str or standard not in SUPPORTED:
        raise ValueError('unsupported-c-language-standard')
    selection = graph.get('selection', {}) if graph is not None else {}
    if 'languageStandard' in selection and selection['languageStandard'] != standard:
        raise ValueError('c-language-standard-dependency-selection-mismatch')
    return standard
