# CV parsing: known gaps

Written after the heading-localization and word-boundary work on branch `import-wizard-1a`
(commits `10bf5d3` import parser, `6c2b8a1` PDF extractor, `f448aad` docs). A record for later;
nothing here is fixed yet.

What that work did: headings and field labels for the import parser
(`python/profile_import/text_parser.py`) and the PDF extractor (`src/utils/profileExtractor.js`)
now come from the language-keyed table `src/data/sectionHeadings.json` (English and Serbian,
Latin and Cyrillic), and skill names are matched as whole terms (`src/utils/termMatch.js`)
instead of as substrings.

## 1. Two parsers still match English headings only

Neither reads `src/data/sectionHeadings.json`.

- `python/resume_generator/resume_parser.py`: finds headings by English stems (`SECTION_STEMS`,
  `STOP_STEMS`). Believed to be correct under the current CV rules (`.claude/rules/resume.md`),
  but that was assumed, not re-checked. Re-check if the rules change, or if a Serbian CV goes
  through tailoring.
- `python/profile_import/linkedin_pdf_mapper.py`: English-only heading patterns. Not verified
  whether it is on an active user-facing path or effectively dead code.

Needs investigation (is it reachable, what does it receive) before deciding whether to port
either one to the shared table.

## 2. Case-insensitive matching still finds "Go" in prose

Whole-term matching fixed `Go` inside `Google`, `ego`, `Django` and `Digitalni`, but matching is
case-insensitive, so ordinary prose such as "go to market" still matches the `Go` skill. The
word-boundary change did not address this. Other dictionary names that are also common words
(`Swift`, `Spark`, `Rust`, `Ruby`, `Jest`, `Mocha`) have the same exposure. A possible fix is
case-sensitive matching for a short list of ambiguous names, at the cost of missing them in
all-caps skills lists.

Related, a deliberate trade-off: a hyphen followed by a letter ends a match, so `go-to-market`
is not `Go`, but `React-based` does not match `React` either.

## 3. Serbian dates are not parsed

Only year-only dates and numeric ranges such as `2024-2025` are recognised. Serbian month names
(`jun`, `sept`, ...) and "present" words (`danas`, `trenutno`, ...) are not, so entries with a
single year, or a month and year, stay as plain unparsed lines in the work-experience list
instead of structured entries with start and end dates. The month and "present" patterns in
`text_parser.py` (`_MONTH`, `_PRESENT`) are English-only and are not in the vocabulary file.

## 4. The skill dictionary is unchanged

`src/data/skillsDictionary.js` is still dev and PM centric. It has no SPSS, SEO, MS Office,
WordPress, Canva, ChatGPT or Google Cloud, and nothing for pedagogy, healthcare, administration
or other non-dev domains. This was out of scope for the heading and matching work and is the
next task. The forced dev/PM candidate archetype and stretch-role logic, and the 60/58 neutral
defaults in `industry_match` and `culture_match`, are also untouched and tracked separately.

## 5. Substring matching remains elsewhere in Python (industries, not skills)

`python/job_scoring/dimensions/industry_match.py` and `red_flags.py` still test industry and
avoided-industry terms with plain substring checks (`term in haystack`). This is a different
purpose from skill matching and was left alone on purpose, not the same bug class. Short terms
there can still collide with longer words, so revisit if industry matching gets false hits.
