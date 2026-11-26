# Package 2: free measurements (2026-11-26)

Four measurements, no product change, no model call, no network. Tool: `scripts/measure_package2.py {profile|steps|prompts|negative}` (reads `/srv/holojob/data` read-only; the scoring profile runs on a copy in a temp dir). Counts, code names and public rule terms only. These numbers feed package 3 (filters), 5 (cost and scoring time) and 6 (deferred detail fetch).

## 1. One scoring pass, profiled (cause of the ~12x slowdown)

**Timeline** (Re-scrape records in `data/analytics/runs`): the free scoring step took 42 s on 2026-11-18 (582 rows), 67-84 s on 2026-11-23, and 515-605 s on 2026-11-24 and 2026-11-26 (3305-3586 rows). Rows grew about 6x, time about 12x, so cost per row doubled as well (72 ms to about 146 ms). The change that added the rows is `eacec8b` (open ads of a search source that the latest search did not return stay scored). A Re-scrape runs the pass up to three times (`scoring-prepare`) plus the final `scoring`: the 2026-11-24 run spent about 1,560 s in three `scoring-prepare` passes and 523 s in the final `scoring`, together more than twice its discovery (911 s).

**Profile** (cProfile, `--workers 1`, because `score_jobs` runs rows on a thread pool that cProfile does not see; 3586 rows; profiled wall time 799 s, inflated by the profiler and by a live Re-scrape sharing the CPU, so it is not the real duration; the shares are what counts):

| Where | Cumulative | Share |
|---|---|---|
| `work_authorization.resolve_places` -> `location_text.read_location` -> `_from_text` | 398 s | 50% |
| of that, `location_text._restrictions` (self 227 s) | 353 s | 44% |
| `text_utils.fold_accents` (char-by-char NFKD, 1.47M calls, 990M `unicodedata.combining` calls) | 205 s | 26% |
| `gates.language_demands` | 92 s | 12% |
| `role_class.label` (Fit 3 anchoring) | 65 s | 8% |

**Cause.** `_restrictions` calls `_fold(text)` (accent folding of the whole ad) inside its loop over the 6 country frames, so each ad is folded 6 times per call, and `resolve_places` is called 3 times per row (`eligibility.assess`, `blocking.location_state`, `work_authorization.authorization_status`; 10,758 calls = 3 x 3586) without a cache. That is 18 folds of an ad of about 6,300 characters per row, in pure Python. All three callers date from 2026-11-17, so the rows (about 6x) explain half the slowdown; the other 2x per row is not isolated by this profile (longer ad text on the ledger-only rows is the likely part; not measured).

**For package 5 (not done here).** Fold once per ad (move `_fold(text)` out of the frame loop) and compute the places once per row; expected to remove most of the 50% above. Neither touches a scoring rule, but the output must be compared row for row first.

## 2. Prompt sections and the shared prefix (1,024 tokens)

No tokenizer is available offline: tokens are estimated at 4 characters (the repo's input floor) and 3 characters (its upper bound). 200 real ledger ads (description over 400 characters; average 6,293 characters).

| Prompt | Template | Text before the first per-ad part | Identical prefix across 200 real prompts | Reaches 1,024 tokens |
|---|---|---|---|---|
| Reading (`enrich_jobs.PROMPT`) | 5,439 chars | 1,129 chars | 27,854 chars (~6,963 tokens at 4/token) | yes |
| Fit 3 classify (`fit3.PROMPT`) | 1,294 chars | 1,031 chars | 1,031 chars (~257 tokens) | **no** |
| Engine (`matcher.PROMPT`) | 3,937 chars | 226 chars | template head only | no |

- Reading: the competency block (20,908 chars, ~5,200 tokens) sits before `{previous}`, `{title}` and the ad, so it is already a shared prefix of about 7k tokens.
- Fit 3: `TITLE` comes first and the lists (roles 401 chars, competencies 15,514 chars, ~3,900 tokens) after it, so the shared prefix is the 1,031-character instruction only. With the lists placed before the title and the ad the shared prefix would be about 16,986 chars (~4,200 tokens). That is a layout change, so it needs the two versions and the Stage A check of the plan (package 5).
- Engine: the ad comes first and the candidate evidence last; evidence is identical across ads but cannot be a shared prefix behind a different ad.
- Whether a provider actually caches a prefix is not measured here (no call).

## 3. LinkedIn detail requests in scan time

Source: the installed jobspy 1.4.0 (`jobspy/linkedin/__init__.py`) and the run records. LinkedIn is read with `fetch_description=True`: one extra `GET /jobs/view/<id>` per search card, no sleep between them, and the 3-7 s sleep only between search pages (10 cards per page). Per-request timings are not recorded anywhere, so this is a model-based estimate, not a measurement.

Run 2026-11-26 (1,114 ads read, 44 searches: 22 returned 50, 12 returned 0, 8 returned 1): the jobspy source took 1,465 s of the 1,530 s discovery step (96%). Sleeps: about 22 searches x 4 gaps x 5 s = 440 s (264-616 s). One page request per search plus the 5 pages of a full search is about 130 requests, an estimated 100-200 s. That leaves **about 825-1,000 s for the 1,114 detail requests: roughly 55-68% of the jobspy source time, about 54-65% of discovery**; discovery is about a fifth of a whole Re-scrape (911 of about 4,100 s on 2026-11-24, the last finished run), so the detail requests are roughly 12-15% of it.

Gain of a deferred fetch (package 6): the detail GET is made for every card, also for the ~9% the title filter then drops (1,114 read, 1,009 kept) and for ads the ledger already holds with a full description. Only 270 of the 1,009 kept were new to the ledger, so fetching details for new and thin ads only would skip up to about 75% of the requests. This is the number package 6 needs; whether jobspy 1.4.0 allows a per-ad fetch (it takes one flag for the whole search) is open.

## 4. Audit of the negative filters per keyword

Source: `career-ops/filter-audit.mjs` (the `unique` metric: offers that one keyword alone catches). Deviations: it audits the negative list (`TITLE_EXCLUDE` of `role_filter.py`), not the positive list; it replays the ledger plus `filtered_ads.json` (7,691 titles: 4,840 ledger, 2,851 filtered only), not a scan history; its score column is replaced by "unique and the only reason" (the title would pass the include, near and search-term lists without this keyword), and the must-keep count. The search terms of the jobspy source are passed as the provider does.

Final decisions on the 7,691 titles: kept 5,112; dropped `title_not_matched` 2,531; dropped `title_excluded` 48. The exclude list is a minor part of the filter: the not-matched rule decides 98% of the drops.

| Keyword | hits | unique | unique and only reason | must-keep hit |
|---|---|---|---|---|
| junior | 22 | 21 | 2 | 0 |
| account manager | 10 | 9 | 0 | 0 |
| sales manager | 7 | 6 | 0 | 0 |
| brand manager | 6 | 5 | 0 | 0 |
| intern | 3 | 3 | 0 | 0 |
| category manager | 1 | 1 | 0 | 0 |
| praktikant | 1 | 1 | 0 | 0 |
| area sales, product technologist, pripravnik | 0 | 0 | 0 | 0 |

Findings: only `junior` is the sole reason for a drop (2 titles, public examples in the report). Six keywords catch titles that would be dropped as not matched anyway (redundant for the current include and search-term lists), three never matched. None of the 19 must-keep ads (Saved, Rejected and Applied ids, an ad with two counted once; Applied ids from the runner's export) has a title with an excluded keyword. Limits: the check is on titles only (the `position` of a board is not in the ledger rows), and a keyword that never matched here may still matter for a source or a day not in the data. Package 3 decides what to do with the list; nothing was changed.
