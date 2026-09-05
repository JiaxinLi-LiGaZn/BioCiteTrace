# The short story

Five static pages follow the reader's question: what does a citation mean, why did we look, how did we read, what did we find, and where can someone look closer?

- `index.html`: the opening question.
- `story.html`: the experience that motivated the review.
- `workflow.html`: a short account of the reading process.
- `findings.html`: the first comparison, using the original Figure 2C.
- `explore.html`: links to the study notes and reusable workflow.

Keep technical instructions in the relevant folder README. Keep result scope visible beside the figure. The HTML pages are the source; no generator, package installation or build service is needed.

## Preview

From the repository root:

```bash
python -m http.server 8000 --directory site
```

Open `http://localhost:8000`. Ordinary links work without JavaScript; left and right arrow keys also turn pages. On small screens, the figure has its own horizontal scroll area. The site respects reduced-motion preferences and uses system fonts, with no analytics or third-party scripts.

## GitHub Pages

The included `.github/workflows/pages.yml` validates and uploads only this folder. It deploys on a change to the website on `main`, or a manual run from `main`. Pull requests validate the pages without publishing them.

In the repository's **Settings → Pages**, choose **GitHub Actions** as the publishing source. The intended URL is `https://jiaxinli-ligazn.github.io/BioCiteTrace/`.

The setup follows [GitHub's static Pages workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). Keep source paper files outside `site/`; only the selected figure and its transcription belong here. See [results provenance](../results/README.md).
