"""`slop agents`: coding-agent CLIs (Claude Code, Codex, Muse Code, Gemini CLI) on the bot's computer or the user's own.

  slop agents status [ENGINE] [--limits]       installed? version? logged in (which plan)? plan usage (no tokens spent)
  slop agents install ENGINE|all [--method M]  into $SLOP_HOME (survives a box wipe); runs as a `slop job`
  slop agents login ENGINE                     headless sign-in: prints the link (and code) for the user
  slop agents login claude --code-from-env CLAUDE_LOGIN_CODE   feeds the pasted code to the waiting sign-in
  slop agents test ENGINE                      one tiny "reply OK" run through runner/deleg.mjs (skipped when logged out)
  slop agents use ENGINE --for director|images|review          the preference, kept in $SLOP_HOME/onboard.json

Modules: engines (facts + finding the binaries), install, login (the sign-in keeper), status (+ plan limits),
prefs (`use`), cli (argparse). Nothing here prints or stores a secret value: only environment variable NAMES.
"""
