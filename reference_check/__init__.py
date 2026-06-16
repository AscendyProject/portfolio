"""Grounded recommendation letter generator.

Composes a recommendation letter from a developer's real, grounded portfolio
work. Every paragraph the letter states must cite evidence that actually exists
in the grounded Portfolio — hallucinated paragraphs are dropped by the grounding
gate and never shipped.
"""
