# {{TITLE}} - decisions

The owner's decisions, dated, newest last. Every storyboard, prompt book and agent brief must honour them.
Quote the owner's words where you can ("too grey", "she sings most lines"): the wording carries the taste.

How to add one (never rewrite or delete an old line - add an UPDATE that supersedes it):

    slop decide "the lead is on screen at least 70 % of the runtime"
    slop decide --supersedes "2026-10-01 14:03" "budget raised to $60 (owner, after the board review)"

Gate approvals (`slop gate board --approve`) and changes to the lead's canon (`slop lead --canon ...`) are logged
here automatically.

## Log

- {{DATE}} - project created (tier {{TIER}}); budget caps set from the tier defaults in project.json - change them only with the owner's OK
