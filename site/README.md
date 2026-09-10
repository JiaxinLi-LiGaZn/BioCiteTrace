# The BioCiteTrace story site

The public site presents the citation-analysis story on one page:

1. the question behind the analysis;
2. the study-level review workflow;
3. the final Figure 2 findings for scVI, scGPT, scGen and GEARS;
4. category-level sampled human-validation results; and
5. links to aggregate data, methods and reusable code.

Figure 1 is outside this website update and is not published in this folder.

## Figure delivery

The page displays the final Figure 2 v13 as a 4,251 × 5,196 pixel PNG exported at 600 dpi. This raster is used in the browser to preserve the exact publication typography and layout. Matching PDF and editable SVG files are available beside it as downloads.

The figure caption keeps the denominators explicit. The result page also explains that N/A marks method-category pairs with no positive labels in the sampled human reference, and that the reported validation values are point estimates without confidence intervals.

## Design

The page uses locally hosted JetBrains Mono, with text of at least 18px outside the original figure. It has a white background, dark text, restrained blue accents and responsive evidence tables. On narrow screens, the full figure scrolls horizontally instead of being compressed until its labels are unreadable.

There are no pagination controls, keyboard interception, animations or third-party runtime requests. Ordinary section links work without JavaScript. The four older chapter URLs redirect to the corresponding anchors so previously shared links remain useful.

## Preview

From the repository root:

```bash
python -m http.server 8000 --directory site
```

Open `http://localhost:8000`. The HTML and CSS are the source; no generator, package installation or build service is needed.

## GitHub Pages

The included `.github/workflows/pages.yml` validates and uploads only this folder. It deploys on a website change to `main`, or a manual run from `main`. Pull requests validate the page without publishing it.

The intended URL is `https://jiaxinli-ligazn.github.io/BioCiteTrace/`.

## Preserve the reading style

Use the established white background, locally hosted JetBrains Mono, dark text of at least 18px, and blue links. Keep the branching reading choices at the top and the workflow connected by plain arrows, without numbered badges or oversized count displays. New findings and figures should fit this style. Keep the AI disclaimer prominent and retain the Tibo acknowledgement.
