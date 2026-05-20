# Conflict Checker uses a JSON lookup table, not vector retrieval

The ingredient conflict checker is the core differentiating Tool. We store conflict pairs in a structured JSON lookup table queried directly by the Tool function, rather than retrieving from the Knowledge Base via embeddings. Ingredient conflicts are a finite, enumerable set of facts; retrieval introduces unnecessary uncertainty (synonym mismatches, chunk boundary effects) for a problem that is better solved deterministically. All other Tools go through RAG as normal.
