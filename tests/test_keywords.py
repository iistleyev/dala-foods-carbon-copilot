"""No hand-tuning to the test set: every rule keyword that occurs in the test ledger also occurs in train."""

from src.load import ROOT, load_ledgers
from src.rules import load_rules


def test_no_rule_keyword_appears_only_in_the_test_ledger():
    df = load_ledgers()
    train_text = " ".join(df.loc[df["set"] == "train", "text"])
    test_text = " ".join(df.loc[df["set"] == "test", "text"])
    keywords = {k for r in load_rules(ROOT / "rules.yaml") for k in r.get("match", [])}
    only_in_test = sorted(k for k in keywords if k in test_text and k not in train_text)
    assert not only_in_test, f"keywords seen only in the test ledger: {only_in_test}"
