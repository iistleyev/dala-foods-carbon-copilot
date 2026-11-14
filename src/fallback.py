"""ML fallback for lines no rule covers.

TF-IDF on character 2-4-grams of (cleaned description + GL account) -> LogisticRegression over
the spend-based factors seen in train. It can only return a spend factor (never EXCLUDE), and the
category follows from that factor, so planted text cannot push a line to 0 through this path."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

LOW_CONFIDENCE = 0.5

# Category implied by each spend factor (from the typical_category column of the factor file).
SPEND_CATEGORY = {
    "SP_TAXI": "S3_C6_TRAVEL", "SP_FREIGHT_ROAD": "S3_C4_TRANSPORT",
    "SP_VEHICLES": "S3_C2_CAPITAL", "SP_MACHINERY": "S3_C2_CAPITAL", "SP_CONSTRUCTION": "S3_C2_CAPITAL",
}


def features(df):
    return (df["text"] + " gl" + df["gl"] + " gl" + df["gl"]).tolist()


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
