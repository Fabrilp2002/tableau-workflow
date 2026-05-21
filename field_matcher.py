"""
field_matcher.py — Compara campos entre dos datasources y sugiere mapeo.

Estrategia de matching (en orden de confianza):
1. Exact match (case-sensitive)
2. Case-insensitive match
3. Camel/snake case equivalence (householdMonthlyIncome ~ household_monthly_income)
4. Fuzzy match por similitud de string (Levenshtein/SequenceMatcher)
5. Match por similitud de samples de datos (cuando los nombres difieren pero los valores son similares)

Para el caso de survey program de your organization:
- Los nombres técnicos de indicadores son muy estables entre encuestas → exact match cubre la mayoría
- Los campos demográficos (Familias) pueden variar → recurrimos a fuzzy + samples
"""

import re
from difflib import SequenceMatcher
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class FieldMatch:
    old_field: str
    new_field: Optional[str]
    confidence: float  # 0.0 - 1.0
    method: str  # 'exact' | 'case-insensitive' | 'normalized' | 'fuzzy' | 'samples' | 'no_match'
    candidates: list = None  # alternativas si confidence < 0.95

    def to_dict(self):
        d = asdict(self)
        d.pop("candidates", None)
        if self.candidates:
            d["candidates"] = self.candidates
        return d


class FieldMatcher:
    """Compara fields de dos datasources y produce mapping con scores."""

    def __init__(self, fuzzy_threshold: float = 0.75, auto_apply_threshold: float = 0.95):
        self.fuzzy_threshold = fuzzy_threshold
        self.auto_apply_threshold = auto_apply_threshold

    @staticmethod
    def _normalize(name: str) -> str:
        """Convierte householdMonthlyIncome → household_monthly_income (todo lowercase, snake_case)."""
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        s = re.sub(r"[\s\-]+", "_", s)
        return s.lower()

    def _string_similarity(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def match(self, old_fields: list[str], new_fields: list[str]) -> list[FieldMatch]:
        """
        Para cada old_field, encuentra el mejor match en new_fields.
        Retorna lista de FieldMatch con confidence y método.
        """
        results = []
        new_set = set(new_fields)
        new_lower = {f.lower(): f for f in new_fields}
        new_norm = {self._normalize(f): f for f in new_fields}

        for old in old_fields:
            # 1. Exact match
            if old in new_set:
                results.append(FieldMatch(old, old, 1.0, "exact"))
                continue
            # 2. Case-insensitive
            if old.lower() in new_lower:
                match = new_lower[old.lower()]
                results.append(FieldMatch(old, match, 0.98, "case-insensitive"))
                continue
            # 3. Normalized (snake/camel)
            if self._normalize(old) in new_norm:
                match = new_norm[self._normalize(old)]
                results.append(FieldMatch(old, match, 0.92, "normalized"))
                continue
            # 4. Fuzzy
            best = None
            best_score = 0.0
            top_candidates = []
            for new in new_fields:
                score = self._string_similarity(old, new)
                if score > best_score:
                    best_score = score
                    best = new
                if score >= self.fuzzy_threshold:
                    top_candidates.append((new, score))

            top_candidates.sort(key=lambda x: -x[1])
            top_candidates = top_candidates[:5]

            if best_score >= self.fuzzy_threshold:
                results.append(FieldMatch(
                    old, best, round(best_score, 3), "fuzzy",
                    candidates=[{"name": n, "score": round(s, 3)} for n, s in top_candidates]
                ))
            else:
                # 5. No match
                results.append(FieldMatch(
                    old, None, 0.0, "no_match",
                    candidates=[{"name": n, "score": round(s, 3)} for n, s in top_candidates]
                ))

        return results

    def refine_with_samples(
        self,
        match: FieldMatch,
        old_samples: list,
        new_field_samples: dict[str, list],
    ) -> FieldMatch:
        """
        Si el match es de baja confianza, compara muestras de datos para mejorar.
        new_field_samples: {field_name: [valores]}
        """
        if match.confidence >= self.auto_apply_threshold:
            return match  # ya está confiable

        if not old_samples or not new_field_samples:
            return match

        old_set = set(str(s) for s in old_samples if s is not None)
        if not old_set:
            return match

        best_overlap = 0.0
        best_field = match.new_field
        for new_field, samples in new_field_samples.items():
            new_set = set(str(s) for s in samples if s is not None)
            if not new_set:
                continue
            # Jaccard similarity
            intersect = len(old_set & new_set)
            union = len(old_set | new_set)
            overlap = intersect / union if union > 0 else 0.0
            if overlap > best_overlap:
                best_overlap = overlap
                best_field = new_field

        if best_overlap > 0.5:
            # Boost de confidence basado en overlap
            new_conf = min(0.99, match.confidence + best_overlap * 0.3)
            return FieldMatch(
                match.old_field, best_field, round(new_conf, 3), f"{match.method}+samples",
                candidates=match.candidates,
            )
        return match

    def summarize(self, matches: list[FieldMatch]) -> dict:
        """Resumen estadístico del resultado del matching."""
        auto = [m for m in matches if m.confidence >= self.auto_apply_threshold]
        fuzzy = [m for m in matches if self.fuzzy_threshold <= m.confidence < self.auto_apply_threshold]
        unmatched = [m for m in matches if m.method == "no_match"]
        return {
            "total": len(matches),
            "auto_applicable": len(auto),
            "needs_confirmation": len(fuzzy),
            "unmatched": len(unmatched),
            "auto_pct": round(100 * len(auto) / len(matches), 1) if matches else 0,
        }
