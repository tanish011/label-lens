from pathlib import Path
from django.conf import settings

ARTIFACT = Path(settings.BASE_DIR) / "ml" / "artifacts" / "product_tfidf.joblib"
MODEL_VERSION = "tfidf-product-text-v1"

def product_text(product):
    return " ".join([product.name, *(category.name for category in product.categories.all()), *(brand.name for brand in product.brands.all())])

def train_artifact(products):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from joblib import dump
    rows = list(products)
    texts = [product_text(product) for product in rows]
    if not texts: raise ValueError("Import products before training product similarity.")
    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(texts)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    dump({"version": MODEL_VERSION, "product_ids": [product.pk for product in rows], "vectorizer": vectorizer, "matrix": matrix}, ARTIFACT)
    return len(rows)

def text_similarities(query_product, candidates):
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        from joblib import load
        candidate_texts = [product_text(product) for product in candidates]
        try:
            artifact = load(ARTIFACT)
            if artifact.get("version") != MODEL_VERSION: raise ValueError("Model version mismatch")
            vectorizer = artifact["vectorizer"]
            query = vectorizer.transform([product_text(query_product)])
            compared = vectorizer.transform(candidate_texts)
        except (OSError, ValueError, KeyError, EOFError):
            vectorizer = TfidfVectorizer(stop_words="english")
            matrix = vectorizer.fit_transform([product_text(query_product), *candidate_texts])
            query, compared = matrix[0:1], matrix[1:]
        return cosine_similarity(query, compared).ravel().tolist()
    except ImportError:
        return None
