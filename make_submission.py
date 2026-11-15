"""Build the submission zip:  python make_submission.py --team 07  ->  Team07_DalaFoods.zip

Packs the code, rules.yaml, masked ledgers, reference CSVs, outputs/, pitch/, data/, tests and README
from the files tracked in git. The raw ledgers, mask_mapping.csv and the Excel data pack carry real
names: the script refuses to build if any of them would end up in the zip. Prints the file list.
"""

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NEVER = {"ledger_train.csv", "ledger_test.csv", "mask_mapping.csv", "DalaFoods_DataPack.xlsx"}
TOP_FILES = {
    "README.md", "requirements.txt", "rules.yaml", "scenarios.yaml", "pytest.ini", "ruff.toml",
    "run.py", "analysis.py", "report.py", "app.py", "stress_test.py", "mask_ledger.py", "make_submission.py",
    "ledger_train_masked.csv", "ledger_test_masked.csv",
    "emission_factors.csv", "categories.csv", "airports.csv", "packaging_specs.csv", "gl_accounts.csv",
    "sample_submission.csv",
}  # fmt: skip
FOLDERS = ("src/", "tests/", "pitch/", "outputs/", "data/", ".streamlit/")


def submission_files() -> list[str]:
    """Files that belong in the submission, sorted: tracked in git, or (in an unzipped copy without git)
    every file under the same names and folders, minus caches."""
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        candidates = tracked.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        candidates = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()]
    keep = [f for f in candidates if (f in TOP_FILES or f.startswith(FOLDERS)) and "__pycache__" not in f]
    return sorted(f for f in keep if (ROOT / f).exists())


def build(team: str, out_dir: Path = ROOT) -> Path:
    """Write Team<team>_DalaFoods.zip into out_dir (default: the project folder) and return its path."""
    files = submission_files()
    leaked = [f for f in files if Path(f).name in NEVER]
    if leaked:
        sys.exit(f"Refusing to build: private files would be included: {leaked}")
    missing = sorted(TOP_FILES - set(files))
    if missing:
        sys.exit(f"Refusing to build: expected files are not tracked in git: {missing}")
    out = Path(out_dir) / f"Team{team}_DalaFoods.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(ROOT / f, f"Team{team}_DalaFoods/{f}")
    return out


def main():
    """Parse --team, build the zip and print its contents."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--team", default="XX", help="team number, e.g. 07")
    args = parser.parse_args()
    if args.team == "XX":
        print("WARNING: no --team given; building TeamXX_DalaFoods.zip. Re-run with --team <number>.")
    path = build(args.team)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    for name in names:
        print(name)
    print(f"\n{len(names)} files -> {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
    assert not any(Path(n).name in NEVER for n in names)
    print("Checked: no raw ledgers, mask_mapping.csv or data pack inside.")


if __name__ == "__main__":
    main()
