# BioCiteTrace

[Read the story →](https://jiaxinli-ligazn.github.io/BioCiteTrace/)

**When an AI model is cited, how is it being used?**

While writing a review of AI in single-cell biology, we spent time with many thoughtful and ambitious methods. Their citation counts reflected considerable interest. Yet in the biological analyses we encountered, some of these models seemed to appear much less often.

That was an impression from our own reading. We wanted to find out whether a closer look at the literature would support it.

So we built **BioCiteTrace**, a workflow for reading the papers behind the citations. Large language models make this kind of review practical across a substantial body of literature, with human review to check the classifications.

## How it works

**Find citing studies → prepare full-text evidence → review independently with LLMs → check a sample with people.**

We ask whether a study applies a method to a biological question, develops it further, evaluates it, uses it in another way, or simply mentions it. For biological applications, we also look for the connection between the method's output and the paper's biological interpretation. Missing evidence stays unresolved.

## What we found so far

Thanks to Tibo for the resets that helped us run the LLM review pipeline across all four methods.

Our first comparison covers scVI, scGPT, scGen and GEARS. Among papers with resolved classifications, biological application was much more common for scVI. For the other three methods, mention only was the most common category.

These are patterns in the reviewed literature. Coverage is incomplete, and agreement with human reviewers varies across categories. The results give us a more specific starting point for discussing adoption.

[See the figure and study notes](results/README.md)

## A closer look

[Try the example](scripts/README.md) · [Read the workflow](docs/README.md) · [Classification rules](codebook/README.md) · [LLM prompts](prompts/README.md) · [Human review](human_reviewers/README.md)
