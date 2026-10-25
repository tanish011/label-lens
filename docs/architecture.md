# Architecture and data flow

1. Browser requests Django templates or JSON endpoints.
2. Catalogue views query the local relational database and paginate results.
3. Search and barcode requests call an isolated Open Food Facts client with bounded timeouts and cache keys.
4. Valid product records are persisted in an atomic service operation. Nutrient values retain decimal value, unit, source, basis and calculated status.
5. The product UI shows source dates, missing-data copy, and calculations only for a declared serving amount.
6. Recommendation ranking first requires a valid priority nutrient on the same basis and category. Optional TF-IDF similarity is a tie-break signal.

## Endpoint notes

See the endpoint list in the README. Public browsing does not require an account. Django Admin requires staff permissions. The API is read-only and throttled for anonymous access.

## Evaluation and limitations

The similarity feature is unsupervised and has no ground-truth labels, so classification accuracy is not reported. Recommendations remain bounded by comparable source nutrient data. Network/provider behavior requires an online run for live verification; local tests mock the response shape.
