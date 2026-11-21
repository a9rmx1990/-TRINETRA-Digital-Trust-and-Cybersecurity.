import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from run_eval import confusion_report, wer, wilson  # noqa: E402


def test_wilson_and_wer():
    assert wilson(0, 0) is None
    lo, hi = wilson(4, 8)
    assert lo < 0.5 < hi
    assert wer("send the otp now", "send otp now") == (1, 4)
    assert wer("a b", "a b") == (0, 2)


def test_confusion_report_counts_both_classes_and_abstention():
    rows = [{"label": 1, "pred": True, "language": "en"}, {"label": 1, "pred": False, "language": "en"},
            {"label": 0, "pred": False, "language": "hi"}, {"label": 0, "pred": True, "language": "hi"},
            {"label": 1, "pred": None, "language": "kn"}]
    r = confusion_report(rows, min_n=2)
    assert r["all"]["tp"] == 1 and r["all"]["fn"] == 1 and r["all"]["fp"] == 1 and r["all"]["abstain"] == 1
    assert r["all"]["recall"] == 0.5 and r["lang:kn"]["recall"] is None
    assert r["all"]["sufficient"] is True and r["lang:en"]["sufficient"] is False


def test_voice_report_keeps_abstentions_in_full_set_rates():
    rows = [
        {"label": 1, "pred": True, "language": "en", "condition": "phone"},
        {"label": 1, "pred": None, "language": "en", "condition": "phone"},
        {"label": 0, "pred": True, "language": "en", "condition": "phone"},
        {"label": 0, "pred": None, "language": "en", "condition": "phone"},
    ]
    phone = confusion_report(rows, min_n=2)["condition:phone"]
    assert phone["synthetic_flag_rate"] == phone["genuine_flag_rate"] == 0.5
    assert phone["synthetic_miss_rate"] == 0
    assert phone["abstain_positive"] == phone["abstain_negative"] == 1
    assert phone["sufficient"] is False
