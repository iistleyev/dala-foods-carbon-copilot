"""The submission zip has the code, rules, masked ledgers, outputs and pitch, and never the raw ledgers."""

import zipfile
from pathlib import Path

import make_submission


def test_zip_contents_and_no_private_files(tmp_path):
    path = make_submission.build("00", tmp_path)
    names = {Path(n).relative_to("Team00_DalaFoods").as_posix() for n in zipfile.ZipFile(path).namelist()}
    assert not {Path(n).name for n in names} & make_submission.NEVER
    for required in ["run.py", "rules.yaml", "ledger_test_masked.csv", "emission_factors.csv", "README.md",
                     "outputs/predictions.csv", "pitch/build_pitch.py", "src/rules.py"]:  # fmt: skip
        assert required in names, required
