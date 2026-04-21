# Sample output

[`sample_output.csv`](./sample_output.csv) is the actual file produced by running
this tool against a Salesforce Developer Edition org with the standard
"Accounts" sample data.

Notice:

- The first two columns (`_org`, `_report`) are injected by the aggregator to
  tag each row with its source — the same rows can be merged across N orgs
  and still be traceable.
- Column headers are in Spanish because the target org's locale was `es_AR`.
  The tool handles any locale without code changes.
- The `"United Oil & Gas, UK"` row has a comma inside a quoted field — CSV
  escaping is preserved end-to-end.
