"""crossverify — a six-phase verification harness for statistical analysis.

The harness runs one analysis through a documented, reproducible protocol:

    1. Data intake and inspection
    2. Transformation sanity checks
    3. Analysis execution + internal consistency checks + spot-checks
    4. Reproducibility (re-run and confirm identical output)
    5. Cross-tool triangulation (compare against an independent R implementation)
    6. Compiled verification log + a ready-to-paste methodology statement

It does not run your analysis for you. You supply the analysis (in Python, and
again in R); the harness orchestrates the runs, checks the numbers, compares the
two implementations, and writes the evidence.
"""

__version__ = "0.1.1"
