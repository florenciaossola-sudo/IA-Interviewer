from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol


class Embedder(Protocol):
    def embed(self, text: str) -> dict[str, float]:
        """Return a sparse token-weight vector."""


class TokenFrequencyEmbedder:
    _token_regex = re.compile(r"[a-zA-Z0-9_]+")

    def embed(self, text: str) -> dict[str, float]:
        tokens = [token.lower() for token in self._token_regex.findall(text)]
        if not tokens:
            return {}

        counts = Counter(tokens)
        norm = math.sqrt(sum(value * value for value in counts.values()))
        if norm == 0:
            return {}

        return {token: value / norm for token, value in counts.items()}
