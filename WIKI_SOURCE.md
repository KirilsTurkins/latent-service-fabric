# LSF Wiki source

The `docs/wiki` branch carries the complete explanatory Wiki under `wiki/pages/` and publishes it to the repository Wiki through `.github/workflows/publish-wiki.yml`.

Canonical technical contracts and decisions remain on the `release` branch. The Wiki is non-normative: do not place unique security requirements, compatibility guarantees, or protocol semantics only here.

## Visual diagram pipeline

Wiki diagrams are authored as animated SVGs by `wiki/visuals/generate_diagrams.py`. The same deterministic generator exports animated GIF previews under `wiki/pages/assets/`, and the Markdown pages embed those previews.

This dual output is deliberate: GitHub Wikis document PNG, JPEG, and GIF as supported image formats, while GitHub's SVG viewer does not run inline SVG scripting or animation. The SVG source remains available for editing and use outside GitHub; the GIF preserves motion in the live Wiki.

The publication workflow regenerates, validates, records, and publishes both formats. It also rejects Mermaid blocks and MediaWiki alias links containing `|` inside Markdown table rows so the two known rendering regressions cannot return unnoticed.

Regenerate locally with:

```bash
python -m venv .wiki-venv
. .wiki-venv/bin/activate
python -m pip install --requirement wiki/visuals/requirements.txt
python wiki/visuals/generate_diagrams.py
```

References:

- [Editing Wiki content: adding images](https://docs.github.com/en/communities/documenting-your-project-with-wikis/editing-wiki-content#adding-images)
- [Working with non-code files: SVG rendering limitations](https://docs.github.com/en/repositories/working-with-files/using-files/working-with-non-code-files#rendering-and-diffing-images)
