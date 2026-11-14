"""Mask counterparty and employee names in the Dala Foods ledgers.

Run locally, once:   python mask_ledger.py
Reads:   ledger_train.csv, ledger_test.csv
Writes:  ledger_train_masked.csv, ledger_test_masked.csv  (safe to share with cloud AI tools)
         mask_mapping.csv                                (KEEP LOCAL - never upload or share)

What gets masked:
  - counterparty column           -> VENDOR_001, VENDOR_002, ...   (stable across both files)
  - employee names in description -> EMP_01, EMP_02, ...           ("Фамилия И." style: surname + initial)
  - sole-proprietor names (ИП X)  -> ИП VENDOR_xxx                 (a person's name inside the text)
Everything else (line_id, doc_no, amounts, units, GL, the rest of the description) is unchanged,
so a pipeline built on the masked files gives the same results as on the raw files.
The script prints only counts, never names.
"""
import re
import pandas as pd

FILES = ["ledger_train.csv", "ledger_test.csv"]

# Surname + one initial, e.g. "Фамилия И." or "Surname A." (Cyrillic or Latin)
EMP_RE = re.compile(r"\b([А-ЯЁӘҒҚҢӨҰҮҺІA-Z][а-яёәғқңөұүһіa-z]+)\s([А-ЯЁӘҒҚҢӨҰҮҺІA-Z])\.")
# Sole proprietor inside a description, e.g. "перевозчик ИП Фамилия"
IP_RE = re.compile(r"\bИП\s+([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+)")


def main():
    dfs = {f: pd.read_csv(f, encoding="utf-8-sig", dtype=str, keep_default_na=False) for f in FILES}
    allrows = pd.concat(dfs.values(), ignore_index=True)

    # Stable codes: sorted so the same name always gets the same code on every run
    vendors = sorted(set(allrows["counterparty"]) - {""})
    ip_names = sorted({m for d in allrows["description"] for m in IP_RE.findall(d)})
    vendor_map = {v: f"VENDOR_{i:03d}" for i, v in enumerate(vendors, 1)}
    for j, name in enumerate(ip_names, len(vendors) + 1):
        vendor_map.setdefault(f"ИП {name}", f"VENDOR_{j:03d}")

    employees = sorted({f"{s} {i}." for d in allrows["description"] for s, i in EMP_RE.findall(d)})
    emp_map = {e: f"EMP_{k:02d}" for k, e in enumerate(employees, 1)}

    def mask_desc(text):
        text = IP_RE.sub(lambda m: "ИП " + vendor_map[f"ИП {m.group(1)}"], text)
        text = EMP_RE.sub(lambda m: emp_map[f"{m.group(1)} {m.group(2)}."], text)
        return text

    for f, df in dfs.items():
        out = df.copy()
        out["counterparty"] = out["counterparty"].map(lambda v: vendor_map.get(v, v))
        out["description"] = out["description"].map(mask_desc)
        out.to_csv(f.replace(".csv", "_masked.csv"), index=False, encoding="utf-8-sig")

    mapping = pd.DataFrame(
        [("vendor", k, v) for k, v in vendor_map.items()] + [("employee", k, v) for k, v in emp_map.items()],
        columns=["type", "original", "code"],
    )
    mapping.to_csv("mask_mapping.csv", index=False, encoding="utf-8-sig")

    # Self-check: no original name may survive in the masked files
    leaks = 0
    for f in FILES:
        masked = pd.read_csv(f.replace(".csv", "_masked.csv"), encoding="utf-8-sig", dtype=str, keep_default_na=False)
        blob = "\n".join(masked["counterparty"]) + "\n" + "\n".join(masked["description"])
        leaks += sum(1 for name in list(vendors) + employees + ip_names if name in blob)

    print(f"Masked {len(vendor_map)} counterparties and {len(emp_map)} employee names "
          f"across {sum(len(d) for d in dfs.values())} lines.")
    print("Self-check:", "OK, no names left" if leaks == 0 else f"WARNING, {leaks} names still present")
    print("Keep mask_mapping.csv local. Work with the *_masked.csv files in cloud AI tools.")


if __name__ == "__main__":
    main()
