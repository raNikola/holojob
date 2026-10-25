# Holojob - Vision

## The problem

Job search tools score a CV by counting keywords. A candidate can game that number,
and a high number still says nothing about whether they can do the job. Recruiters
mostly do not auto-reject on keyword scores; they look for evidence of relevant work.
Meanwhile the candidate spends hours on postings that were never a fit, and loses track
of where each application stands.

## The idea

Holojob answers one question for every posting:

> Based on what I have actually done, how much evidence do I have that I meet this job?

It reads a posting into its requirements, finds the evidence for each in the candidate's
own history, and lets deterministic code compute the score. Every number can be traced to
a requirement, a status and a quote. Unknown is not missing: what the system cannot tell
becomes a question, and every answer makes the profile better for the next posting.

## What it is

- **An evidence-based matching engine.** AI marks facts with quotes; code computes the
  score, applies hard rules (work authorization, location, role family) and reports how
  complete its answer is.
- **A profile that is a bank of evidence**, not a list of buzzwords. A CV is one view of it.
- **One place for the whole search**: discovery (including Serbian job boards and remote
  roles open to Serbia), ranking, application tracking, interview preparation, CV and cover
  letter tailoring that never invents a fact.
- **Self-hosted and private.** Personal identifiers never leave the server.

## What it is not

- Not an auto-apply bot. The candidate decides and presses Submit.
- Not a keyword optimizer. CV keyword coverage is shown separately and never inflates fit.
- Not a predictor of being hired. The score is a priority for where to spend time.

## Who it is for

First, its author: a senior / technical product manager in Niš, Serbia, looking for remote
or near-remote work. Then colleagues in other role families - engineering, design, QA,
data - who can use the same engine through role-family configuration instead of code changes.
