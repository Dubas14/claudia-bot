"""slop.sync — lip sync as an audio check (avsync port), sung-seconds coverage and cover proposals.

Seedance in reference mode copies the reference audio into its own soundtrack and the mouth follows that soundtrack,
so whether the lips match the song is measured by comparing the take's audio with the window it was conditioned on.
See `slop.sync.avsync` (the measurement) and `slop.sync.coverage` (what is still uncovered and how to cover it).
"""
