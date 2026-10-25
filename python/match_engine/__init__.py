"""The Phase 1 scoring engine (docs/redesign/ENGINE_CONTRACT.md).

This step holds the matcher (contract section 2, step 3) and the code that
verifies its quotes (section 5.2). Fit, confidence, labels, caps and the gate
bucket are later steps.

The engine reuses job_scoring's text folding, provider plumbing and ad
fingerprint rather than keeping copies of them.
"""

import sys
from pathlib import Path

_PYTHON = Path(__file__).resolve().parents[1]
for _sub in ("job_scoring", "cv_analysis"):
    _path = str(_PYTHON / _sub)
    if _path not in sys.path:
        sys.path.append(_path)
