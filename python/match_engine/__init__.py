"""The Phase 1 scoring engine (docs/redesign/ENGINE_CONTRACT.md).

The matcher (contract section 2, step 3), the code that verifies its quotes
(section 5.2), the gates (gates.py, section 5.4) and Fit, confidence, caps,
bucket and label (fit.py, sections 5.1, 5.3-5.5). Not wired into a run yet.

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
