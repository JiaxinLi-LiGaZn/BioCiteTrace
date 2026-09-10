# The short story

One page offers several ways into BioCiteTrace. The reading choices appear directly beneath the opening question, before the longer story:

- **Read the story** jumps to the experience that motivated the review.
- **See the findings** jumps to Figure 2C, with a direct link to the study notes.
- **Explore the workflow** jumps to the short process description and links to the methods and prompts.
- **Try the example** opens the runnable example instructions; the code is one link away.

Readers can follow those branches or continue down the page through the story, workflow and findings. Technical instructions stay in their folder READMEs. The original result figure and its scope are preserved.

## Design

The page has a white background, dark text and blue links. Headings and body text use locally hosted **JetBrains Mono**. Text outside the original figure is at least 18px, including navigation, captions and source notes. On narrow screens the figure scrolls horizontally instead of reducing its labels to tiny text.

There are no pagination controls, keyboard interception, animations or third-party runtime requests. Ordinary section links work without JavaScript. The four old chapter URLs redirect to the corresponding anchors so previously shared links remain useful.

The font files come from [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) and are distributed under the [SIL Open Font License](assets/fonts/OFL.txt). Technical-document links point to the main branch on GitHub.

## Preview

From the repository root:

```bash
python -m http.server 8000 --directory site
```

Open `http://localhost:8000`. The HTML and CSS are the source; no generator, package installation or build service is needed.

## GitHub Pages

The included `.github/workflows/pages.yml` validates and uploads only this folder. It deploys on a website change to `main`, or a manual run from `main`. Pull requests validate the page without publishing it.

In the repository's **Settings → Pages**, choose **GitHub Actions** as the publishing source. The intended URL is `https://jiaxinli-ligazn.github.io/BioCiteTrace/`.

The setup follows [GitHub's static Pages workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). Keep source paper files outside `site/`; only the selected figure belongs here. See [results provenance](../results/README.md).

## Approved backup and current results

Commit `d408404` is the approved reading-style baseline. The stylesheet is restored verbatim from that backup. Preserve its opening, branching navigation, four-step workflow, short findings section, horizontal Panel C, validation-table layout and footer when adding results.

All four methods now have sampled human-validation results. Their category-level tables use `results/figure_2_human_validation.csv`, including N/A where the human sample has no positive labels. Removed macro averages are not restored. The original horizontal Panel C remains the homepage image; its category values are unchanged. The complete updated Figure 2 v13 remains available as high-resolution PNG, PDF and editable SVG downloads. Its source files and provenance are unchanged.
