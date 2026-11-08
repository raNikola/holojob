"""The read vocabulary of a source (Wave 1 safety rule). Standard library only: run_log and staging use it without the providers' dependencies."""

# The read vocabulary. Only "ok" (ads were read) and, per board, a complete read can support closing; nothing here closes an ad by itself.
READ_OK = "ok"  # ads were read
READ_CONFIRMED_EMPTY = "confirmed_empty"  # every part answered successfully and held no ads; held, never a reason to close
READ_INCOMPLETE = "incomplete"  # throttled, partial, timeout, blocked, or "ok with 0 read" that nothing confirms
READ_FAILED = "failed"  # nothing could be read
READ_SKIPPED = "skipped"
READ_CLASSES = (READ_OK, READ_CONFIRMED_EMPTY, READ_INCOMPLETE, READ_FAILED, READ_SKIPPED)


def classify_read(outcome) -> str:
    """The read class of an outcome. A provider that knows better sets `read_class`; otherwise it is derived, and a plain
    `ok` with nothing read is INCOMPLETE, not empty: a soft block looks exactly like that."""
    declared = getattr(outcome, "read_class", None)
    if declared in READ_CLASSES:
        return declared
    status = outcome.status
    if status == "skipped":
        return READ_SKIPPED
    if status == "failed":
        return READ_FAILED
    if status == "partial":
        return READ_INCOMPLETE
    return READ_OK if outcome.read > 0 else READ_INCOMPLETE
