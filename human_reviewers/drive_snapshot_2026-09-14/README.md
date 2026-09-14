# Google Drive review record snapshot

This directory preserves the retained review documents from the Google Drive search on 14 September 2026. Superseded unfilled forms are excluded. Start with the [complete catalog](../CATALOG.md) for the source links, file roles, and completion limits.

- `inventory.json` describes 14 source documents and their observed status.
- `MANIFEST.tsv` records the sizes and SHA-256 checksums of 45 files: 28 original DOCX/PDF exports, 14 extracted table files, and 3 case-level TSV files. Four of the original exports are the existing scGPT backups in `../completed/`; they are referenced without duplication.
- Each new source document is preserved as an unedited Google Drive DOCX export and PDF export.
- `*.tables.json` preserves the DOCX paragraphs, table cells, hyperlink relationship targets, source DOCX path, and source DOCX checksum. Repeated page headers remain present. These files are deterministic text extractions, not new scientific reviews.
- The scVI and scGen consensus TSVs preserve the recorded case-level text. The GEARS TSV preserves the working coordinator columns, including unresolved and blank fields. Newlines within cells are quoted according to TSV/CSV conventions; use a proper parser rather than splitting lines.

Extraction reads `word/document.xml` and `word/_rels/document.xml.rels` from each DOCX ZIP. Paragraph text is the concatenation of `w:t` nodes; table-cell paragraphs are separated by newlines. Only rows whose first cell contains an `HV` or `CAL` record ID enter the case-level TSVs. Table and row indices are zero-based positions within the exported DOCX. Labels are not normalized, filled in, reconciled, or joined to machine predictions during extraction.

The export date for the existing scGPT reviewer files remains 27 August 2026. Their source modification times were rechecked on 14 September and are unchanged. New exports were made on 14 September. Source modification timestamps were checked again after export; the connector did not return native Google Docs revision IDs for this new snapshot.

Original blank fields, inconsistent status markings, provisional estimates, and historical pipeline counts are retained. The catalog explains how these differ from the manuscript figure. None of these copies was written back to Google Drive.

Validation checked every DOCX ZIP, every PDF's readable case-ID set, case-ID uniqueness in the relevant tables, source timestamps, and file checksums. This is a content-preservation check; no new full-text scientific adjudication or corpus-wide model run was performed.
