"""slop review — the safety and canon scan of every generated take, done by the bot (or the safety-scan workflow).

Commands (slop/review/cli.py): `slop review scan-sheets` · `slop review record FILE` · `slop review status`.

  scan-sheets  the takes the edit plays (edit/edl.json → clips/<clip>.json takes) → render/scan-list.json (the list
               the safety-scan workflow reads) and ONE 3×2 contact sheet per take at 8 / 25 / 42 / 58 / 75 / 92 % of its
               length, 640 px tiles labelled with the time → render/scan/<clip>-t<k>.jpg (+ --plates: the picked plates
               the edit shows, six to a sheet → render/scan/plates-NN.jpg), and render/scan/findings-template.json
               (the names under "to_check", "checked" empty: nothing counts until someone looks)
  record FILE  the findings (the workflow's result, an agent's slice, or the bot's own copy of the template filled in,
               render/scan/findings.json) checked against the schema in templates/workflows/safety-scan.js, merged into
               render/scan/scan.json; a re-scan of a re-made take replaces that take's findings; takes no longer in the
               edit are marked stale; the template itself (or an unchanged copy) is refused
  status       the verdict against the takes the edit plays NOW: takes checked, re-made since, a changed edit, open
               blocks / fixes, the release verdict (the same rule as `slop status`)
Rubric and triage: docs/80-review-qa.md §9. No network, no spend.
"""
