"""ML fallback for lines no rule covers.

TF-IDF on character 2-4-grams of (cleaned description + GL account) -> LogisticRegression over
the spend-based factors seen in train. It can only return a spend factor (never EXCLUDE), and the
category follows from that factor, so planted text cannot push a line to 0 through this path."""
import difflib
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

LOW_CONFIDENCE = 0.5
TYPO_CUTOFF = 0.8  # "фрион" vs "фреон" = 0.8


def possible_typo(text: str, keywords) -> str | None:
    """A word that is a near miss of a measured-item keyword ("фрион" ~ "фреон"), or None.
    Only single-word keywords of 5+ letters are compared; words are cut to the keyword's length."""
    stems = [k for k in keywords if len(k) >= 5 and " " not in k]
    for word in re.findall(r"[^\W\d_]{4,}", text.lower()):
        for stem in stems:
            if stem in word:
                continue
            ratio = max(difflib.SequenceMatcher(None, word[:len(stem) + d], stem).ratio() for d in (0, 1))
            if ratio >= TYPO_CUTOFF:
                return stem
    return None

# Category implied by each spend factor (from the typical_category column of the factor file).
SPEND_CATEGORY = {
    "SP_TAXI": "S3_C6_TRAVEL", "SP_FREIGHT_ROAD": "S3_C4_TRANSPORT",
    "SP_VEHICLES": "S3_C2_CAPITAL", "SP_MACHINERY": "S3_C2_CAPITAL", "SP_CONSTRUCTION": "S3_C2_CAPITAL",
}


# Masking codes, the name-field words in front of them and legal designators say nothing about what
# was bought, but their letters can steer the char n-gram model ("сотрудник EMP_04" looks like
# "питание сотрудников", the caterer). They are removed before the model sees the text.
NOT_THE_PURCHASE = re.compile(
    r"(?:\b(?:employee|passenger|travell?er|supplier|provider|сотрудник|пассажир|қызметкер|поставщик)"
    r"\s*[:=]?\s*)?\b(?:vendor|emp)_\d+\b|\b(?:ип|тоо|ао|too|llp|llc)\b")


def features(df):
    text = df["text"].str.replace(NOT_THE_PURCHASE, " ", regex=True)
    return (text + " gl" + df["gl"] + " gl" + df["gl"]).tolist()


class SpendFallback:
    def __init__(self):
        self.model = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True),
            LogisticRegression(max_iter=3000, C=10.0),
        )

    def fit(self, train_df):
        spend = train_df[train_df["y_ef_id"].fillna("").str.startswith("SP_")]
        self.model.fit(features(spend), spend["y_ef_id"])
        return self

    def predict(self, df):
        """-> list of (ef_id, category, probability)"""
        proba = self.model.predict_proba(features(df))
        classes = self.model.classes_
        out = []
        for p in proba:
            i = p.argmax()
            ef = classes[i]
            out.append((ef, SPEND_CATEGORY.get(ef, "S3_C1_GOODS"), float(p[i])))
        return out
