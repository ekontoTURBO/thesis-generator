Use NotebookLM. CORRECTION MODE — apply fixes to existing citations in subsection **{{section_id}}**.

You are NOT writing new content. You are FIXING specific citations that an audit has flagged. For each fix below:

1. Open the named source in this notebook.
2. Find the actually correct page / claim.
3. Return a "PRZED → PO" replacement sentence with the corrected attribution.

If the source doesn't actually support the claim:
- Propose an alternative source from the library, OR
- Mark the sentence for deletion.

## Output format (exact, per fix)

```
#### Poprawka 1. [P0XXX]
PRZED: "<current sentence verbatim>"
PO: "<corrected sentence verbatim>"
KOMENTARZ: <1-2 sentences with literal quote from source>
ZMIANA W BIBLIOGRAFII (if applicable): <full corrected APA entry>
```

## Fixes to apply

{{fixes_list}}
