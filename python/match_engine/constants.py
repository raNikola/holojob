"""Every number the engine's Fit, confidence, caps and label rest on (contract 5.1, 5.3, 5.5).

Set in step 7 against tests/fixtures/postings/ (ENGINE_CONTRACT.md, Open
points 1): one matcher run on the owner's evidence index, re-scored offline
with python/match_engine/calibrate.py. Still a proposal until the owner has
reviewed the fixture results; the engine stays in shadow mode meanwhile.
tests/python/test_engine_snapshot.py shows what any change here moves.
Any change here changes results, so it bumps ENGINE_VERSION (section 6).

Values are Fractions, not floats, so Fit is computed in exact rational
arithmetic and the same inputs always round the same way (see fit.py).
"""

from fractions import Fraction as F

ENGINE_VERSION = "0.2.0"

# Credit a requirement earns per evidence strength 0-4 (section 4.3), the same
# for every requirement: none, claim, contextual, demonstrated, with outcome.
# Demonstrated work earns nearly full credit: whether a bullet carries a
# number (4 rather than 3) says more about how the CV is written than about
# the fit, so the qualitative step is between mentioned (2) and done (3).
STRENGTH_CREDIT = (F(0), F(1, 4), F(1, 2), F(9, 10), F(1))

# Weight of a requirement in Fit and confidence, by importance (section 4.2).
# A must counts three times a nice-to-have. The extractor marks most
# requirements must (126 of 161 on the fixtures), so this barely moves Fit.
IMPORTANCE_WEIGHT = {"must": F(3), "preferred": F(2), "nice": F(1)}

# Share of its strength credit a PARTIAL earns: it covers part of what is
# asked, so half the credit of a MET at the same strength.
PARTIAL_FACTOR = F(1, 2)

# Confidence below this makes the label Incomplete: under half of the weight
# judged (requirements and gates) rests on a verified status.
MIN_CONFIDENCE = F(1, 2)

# UNKNOWN musts divided by all musts above this makes the label Incomplete:
# more than one must in three cannot be settled from the profile.
MAX_UNKNOWN_MUST_RATIO = F(1, 3)

# Label from Fit when the result is not Incomplete; a Fit at the threshold
# gets the higher label. Reference points under the credits above:
#   Strong 75: two thirds MET and one third PARTIAL, all demonstrated.
#   Good 45:   every requirement PARTIAL with demonstrated work behind it.
#   Partial 30: above a profile that only claims everything (all MET at
#              strength 1, or all PARTIAL at 2, is 25: Weak).
LABEL_STRONG_MIN = 75
LABEL_GOOD_MIN = 45
LABEL_PARTIAL_MIN = 30

# Fit ceilings (section 5.5). When both apply, Fit is held to the lower one.
# A posting outside the candidate's role family is the wrong job however well
# the evidence covers it: kept under LABEL_GOOD_MIN, so at most Partial.
ROLE_MISMATCH_FIT_CAP = 40
# Not one requirement rests on a quote code found in the candidate's own
# text: kept under LABEL_PARTIAL_MIN, so at most Weak. A backstop: the
# downgrade rule (section 5.2) already holds such a Fit near 12.
UNVERIFIED_FIT_CAP = 25
