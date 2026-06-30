"""Case Element Flagging & Intake Support Engine.

A proof-of-concept that takes a wrongful-conviction intake questionnaire,
retrieves the matching public court records, and flags individual case elements
that match documented structural-failure patterns (per the National Registry of
Exonerations). It is a triage aid for human attorney review: each element is
flagged on its own, never combined into a composite score and never ranked. See
READMEv2.md sections 2, 3 and 6 - those constraints are binding on every module
here.
"""

__version__ = "0.1.0"
