"""The five gates a ticket passes between dispatch and landing.

  1. red proof   TDD is verified, not trusted
  2. suite       no regressions against the run's baseline, plus the flake amendment
  3. scope       declared files vs touched files — a soft gate
  4. review      two-axis review, gated on blocker count
  5. overlap     mechanical AST check for two agents writing the same symbol

Each is mechanical. Each returns a result object rather than deciding policy;
the run loop reads those and decides.
"""
