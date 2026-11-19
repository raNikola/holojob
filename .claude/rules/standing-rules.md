# Standing rules (owner, 2026-11-19; override earlier habits)

No `paths:` filter: loads in every session.

1. **Limits are stop points, not obstacles.** If any limit (daily USD, call count, monthly, rate limit, anything else) blocks you or would make you wait for a reset: stop immediately. Report what is blocked, how much is left, and what is needed to continue. Wait for the owner's decision. Do not sleep until reset, do not reorder work to get around a limit, do not change limits yourself.
2. **Tests do not run on every change.** The full suite (Python, Vitest, build) runs only periodically: after a larger feature is finished, or when the owner explicitly asks. For small changes run only the targeted test for the file touched (if one exists), or none and say so. Never hold a report waiting on the full suite.
3. **Build, up and push are the owner's.** Do not run `podman-compose build/up` and do not `git push`. Finish at the commit (and tag if agreed), give the exact commands to run (fish shell, DS9), and stop. Exception only when the owner explicitly asks in that message.
4. **A new test is written only for a rule or bug that would hurt the owner** (eligibility and blocking, privacy and data handling, scoring contracts, deploy checks, a regression that was real). Never to pin implementation, UI text, markup, class names, source text or pinned numbers; prefer an invariant over a snapshot.
5. If any of this is a problem for the current task, stop and ask. Do not work around it.
