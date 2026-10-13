"""slop.gen — generation through OpenRouter (images, image edits, video clips, Lyria songs), HTTPS hosting for references,
the Higgsfield request-file path (the bot runs the MCP calls) and the clip lifecycle (clips/<id>.json).

No paid call is ever made without: an estimate, the project budget check (slop.ledger.check_budget) BEFORE the call,
--yes (or the project's prompts_approved gate for clips), and — for clips — status "locked". Every spend is ledgered.
Model/weight licences: none bundled (all generation is remote; outputs follow each provider's terms — Lyria: Google
claims no ownership but grants no explicit commercial licence; Seedance/OpenRouter: provider terms).
"""
