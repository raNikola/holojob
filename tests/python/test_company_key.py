"""The company key (package 3): the repost counter (package 7) groups by it, so two spellings of one employer must meet and two
employers must not. Invariants, not a list of names."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python" / "job_scoring"))

import company_key as ck  # noqa: E402


def test_legal_form_case_punctuation_and_country_do_not_split_one_employer():
    keys = {ck.company_key(n) for n in ("Nordeus d.o.o.", "NORDEUS DOO", "Nordeus", "Nordeus Serbia", "Nordeus (Belgrade)")}
    assert keys == {"nordeus"}


def test_a_country_that_names_the_employer_stays_and_a_name_never_keys_empty():
    assert ck.company_key("Bank of Serbia") == "bank of serbia"
    assert ck.company_key("Solutions") == "solutions", "a descriptor alone is the name"
    assert ck.company_key("!!!") and ck.company_key("Яндекс") == "яндекс"
    assert ck.company_key("") == "" and ck.company_key(None) == ""


def test_a_stored_key_wins_and_an_old_row_falls_back_to_its_company():
    assert ck.key_of({"companyKey": "x", "company": "Acme Ltd"}) == "x"
    assert ck.key_of({"company": "Acme Ltd"}) == "acme"
    assert ck.key_of({"job": {"company": "Acme GmbH"}}) == "acme", "a ledger entry keeps the company in its ad snapshot"
