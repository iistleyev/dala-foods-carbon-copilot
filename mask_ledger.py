"""Create both masked ledgers locally. Keep the reversible mask_mapping.csv private."""
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

FILES = ("ledger_train.csv", "ledger_test.csv")
UPPER = "A-ZА-ЯЁӘҒҚҢӨҰҮҺІ"
LOWER = "a-zа-яёәғқңөұүһі"
LETTERS = UPPER + LOWER
# Separate title-case names from all-caps names so "Преформа ПЭТ" or
# "Авиабилет ALA-NQZ" cannot be mistaken for a person.
TITLE = rf"(?:[{UPPER}][{LOWER}]+|[{UPPER}]['’][{UPPER}][{LOWER}]+)(?:[-'’][{UPPER}]?[{LOWER}]+)*"
CAPS = rf"[{UPPER}]{{2,}}(?:[-'’][{UPPER}]+)*"
WORD = rf"(?:{TITLE}|{CAPS})"
INITIAL = rf"[{UPPER}]\."
PERSON = re.compile(
    rf"(?<![\w-])(?:{TITLE}\s+(?:[{UPPER}]\.?\s+){{1,2}}{TITLE}|"
    rf"{WORD}\s+(?:{INITIAL}\s*){{1,3}}|(?:{INITIAL}\s*){{1,3}}{WORD}|(?:{INITIAL}\s*){{2,3}}|"
    rf"{TITLE}(?:\s+(?:(?:de|van|von|bin)\s+)?{TITLE}){{1,3}}|{CAPS}(?:\s+{CAPS}){{1,3}})"
    rf"(?![\w-])"
)
PERSON_FIELD = re.compile(
    rf"(?i:\b(?:employee|passenger|travell?er|сотрудник|пассажир|қызметкер))\s*[:=]\s*"
    rf"([{LETTERS}][-'{LETTERS}’.]*(?:\s+[{LETTERS}][-'{LETTERS}’.]*){{1,3}})"
)
LEGAL = r"(?i:ТОО|TOO|ИП|АО|AO|LLP|LLC)"
MARKER = re.compile(rf"\b{LEGAL}\b")
QUOTED = r"""(?:«[^»\n]+»|“[^”\n]+”|"[^"\n]+"|'[^'\n]+')"""
QUOTED_COMPANY = re.compile(rf"(?:\b{LEGAL}\s*{QUOTED}|{QUOTED}\s*{LEGAL}\b)")
ORG_WORD = rf"[{LETTERS}0-9][\w&’'-]*"
# A legal suffix ends an entity. For unfamiliar unquoted lowercase names the
# field delimiter is the safe boundary; preserve common surrounding invoice terms.
ORG_PART = rf"(?!(?i:from|for|via|by|at|and|от|для|через|и)\b){ORG_WORD}"
SUFFIX_COMPANY = re.compile(rf"(?<!\w){ORG_PART}(?:\s+(?:&\s+)?{ORG_PART})*\s+{LEGAL}\b")
PREFIX_COMPANY = re.compile(rf"\b{LEGAL}\s+{ORG_PART}(?:\s+(?:&\s+)?{ORG_PART})*")
TOKEN = re.compile(r"\b(?:VENDOR|EMP)_\d+\b")


def _known_names(names):
    variants = sorted({name for name in names if name.strip()}, key=len, reverse=True)
    if variants:
        return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, variants)) + r")(?!\w)", re.I)
    return None


class LedgerMasker:
    def __init__(self, counterparties):
        names = sorted({name for name in counterparties if name.strip()})
        self.vendors = {name: f"VENDOR_{i:03d}" for i, name in enumerate(names, 1)}
        self.employees = {}
        # Recognise the registered name both with and without its legal designator.
        self.aliases = {}
        for name, code in self.vendors.items():
            bare = MARKER.sub("", name).strip(' «»“”"\x27')
            for alias in (name, bare):
                if alias:
                    self.aliases.setdefault(alias.casefold(), code)
        self.known = _known_names(self.aliases)
        self.full_names = _known_names(name for name in names if MARKER.search(name))

    def _code(self, original, mapping, prefix, width):
        if original not in mapping:
            mapping[original] = f"{prefix}_{len(mapping) + 1:0{width}d}"
        return mapping[original]

    def mask_desc(self, text):
        def company(match):
            original = match[0].strip()
            alias = original.casefold()
            if alias in self.aliases:
                return self.aliases[alias]
            return self._code(original, self.vendors, "VENDOR", 3)

        def employee(name):
            return self._code(name.strip(), self.employees, "EMP", 2)

        # Match known full counterparty names first, even when case or quoted
        # spelling differs. Leave bare aliases until after legal designators.
        if self.full_names:
            text = self.full_names.sub(lambda m: self.aliases[m[0].casefold()], text)
        text = QUOTED_COMPANY.sub(company, text)
        text = SUFFIX_COMPANY.sub(company, text)
        text = PREFIX_COMPANY.sub(company, text)
        if self.known:
            text = self.known.sub(lambda m: self.aliases[m[0].casefold()], text)
        text = PERSON_FIELD.sub(lambda m: m[0][:m.start(1)-m.start()] + employee(m[1]), text)
        return PERSON.sub(lambda m: employee(m[0]) + (" " if m[0][-1].isspace() else ""), text)

    def validate(self, ledgers):
        known = _known_names([*self.aliases, *self.vendors, *self.employees])
        for df in ledgers:
            for row in df.itertuples():
                if row.counterparty and not re.fullmatch(r"VENDOR_\d+", row.counterparty):
                    raise ValueError(f"Unmasked counterparty at {row.line_id}")
                rest = TOKEN.sub("|", row.description)
                if (MARKER.search(rest) or PERSON.search(rest) or PERSON_FIELD.search(rest)
                        or (known and known.search(rest))):
                    raise ValueError(f"Unresolved name or legal designator at {row.line_id}")


def main():
    inputs = {f: pd.read_csv(f, encoding="utf-8-sig", dtype=str, keep_default_na=False) for f in FILES}
    masker = LedgerMasker(pd.concat(inputs.values())["counterparty"])
    for df in inputs.values():
        df["counterparty"] = df["counterparty"].map(lambda name: masker.vendors.get(name, ""))
        df["description"] = df["description"].map(masker.mask_desc)
    masker.validate(inputs.values())  # check both splits before publishing either file

    mapping = [(kind, name, code) for kind, names in (("vendor", masker.vendors), ("employee", masker.employees))
               for name, code in names.items()]
    with TemporaryDirectory(dir=".") as temp:
        staged = Path(temp)
        for name, df in inputs.items():
            df.to_csv(staged / name.replace(".csv", "_masked.csv"), index=False, encoding="utf-8-sig")
        key = staged / "mask_mapping.csv"
        pd.DataFrame(mapping, columns=["type", "original", "code"]).to_csv(key, index=False, encoding="utf-8-sig")
        key.chmod(0o600)
        for output in staged.iterdir():
            output.replace(output.name)
    print(f"Masked {len(masker.vendors)} vendors and {len(masker.employees)} employees across both ledgers.")


if __name__ == "__main__":
    main()
