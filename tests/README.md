# Offline checks

From the repository root:

```bash
python -m pip install -e '.[upstream]'
PYTHONPATH=src python -m unittest discover -s tests -v
```

The full suite needs the optional XML reader. It uses synthetic files, injected source responses and mocked model calls; no real literature retrieval or LLM review is performed.

The checks cover capsule construction, rights assertions, grounded quotations, multi-label consistency, blind comparison, conditional third review, durable execution state, source snapshots, manual-review gates, retrieval handoff and category scoring.

Passing these tests does not establish real-document parsing quality, live API compatibility or scientific classification performance. Those need a prepared real pilot and independent human review.
