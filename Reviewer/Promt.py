"""
Promt.py — Generación del prompt principal de SIRA.

Cambio de paradigma:
  ANTES: puntuaciones por dimensión → comentario genérico derivado de la puntuación.
  AHORA: extractos concretos del paper → razonamiento sobre cada uno → problemas
         identificados con cita textual → el veredicto emerge del análisis, no al revés.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Secciones esperadas en el output (para validación en otros módulos)
# ---------------------------------------------------------------------------
SECCIONES_REQUERIDAS = [
    "# 1. Research Fingerprint",
    "# 2. Targeted Findings",
    "# 3. Cross-Section Issues",
    "# 4. Methodology Interrogation",
    "# 5. Reproducibility Audit",
    "# 6. Required Actions",
    "# 7. Final Verdict",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_sections(sections: dict[str, str]) -> str:
    """Serializa el dict de secciones segmentadas para insertarlo en el prompt."""
    if not sections:
        return "(no section segmentation available — reason over the full text)"

    lines: list[str] = []
    for label, content in sections.items():
        lines.append(f"<section id='{label}'>")
        lines.append(content.strip())
        lines.append(f"</section>")
        lines.append("")
    return "\n".join(lines)


def _format_rag(similar_reviews: list[dict]) -> str:
    """Formatea el contexto RAG de SciPost."""
    if not similar_reviews:
        return ""

    parts = ["<reference_reviews>"]
    parts.append(
        "Real peer reviews from SciPost on comparable papers. "
        "Use them to calibrate tone, depth, and what real reviewers focus on. "
        "Do NOT copy them. Do NOT mention them in your output.\n"
    )
    for i, r in enumerate(similar_reviews, 1):
        parts.append(
            f"[Reference {i} — '{r['title']}' | {r['journal']} | "
            f"similarity={r['similarity']}]"
        )
        # Truncar para no explotar el contexto
        parts.append(r["review_text"][:700])
        if i < len(similar_reviews):
            parts.append("---")
    parts.append("</reference_reviews>\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Builder principal
# ---------------------------------------------------------------------------

def build_prompt(
    paper_text: str,
    similar_reviews: list[dict],
    sections: dict[str, str] | None = None,
) -> str:
    """
    Construye el prompt completo para el LLM revisor.

    Args:
        paper_text:      Texto completo del paper (fallback si sections está vacío).
        similar_reviews: Reviews recuperadas de ChromaDB para calibración.
        sections:        Dict {label: contenido} con el paper ya segmentado por sección.
                         Si se provee, los agentes razonan sobre secciones concretas.
    """
    rag_block = _format_rag(similar_reviews)
    sections_block = _format_sections(sections or {})

    prompt = f"""You are an expert academic peer reviewer for IEEE, Nature, and ACM journals.

Your job is NOT to fill a scorecard. Your job is to read specific passages from this paper,
identify concrete problems, and explain exactly what is wrong and why — citing the text directly.

{rag_block}
## HOW TO REASON (internal — do not output these steps)

For each section of the paper:
  1. Read it carefully.
  2. Ask: Is there a claim here that is not justified? An assumption left unstated?
     A conclusion that does not follow from the evidence? A comparison that is unfair?
     A term used inconsistently? A number that looks suspicious?
  3. If yes, mark it as a FINDING — copy the specific phrase or sentence, then explain the problem.
  4. If no significant issue, note what makes the section solid.

Do not evaluate in the abstract. Every observation must be anchored to something you can quote.

## SEGMENTED PAPER

{sections_block}

<full_paper_fallback>
{paper_text[:6000]}
</full_paper_fallback>

---

## OUTPUT FORMAT (follow exactly, in this order)

# 1. Research Fingerprint
One tightly written paragraph identifying: the exact research question, the proposed approach,
what distinguishes it from prior work (or fails to), and what would need to be true for the
paper's central claim to hold. No filler. No praise for its own sake.

# 2. Targeted Findings

For each significant finding, use this structure (repeat as many times as needed; minimum 4):

## Finding [N]: [Short label, e.g. "Unsupported baseline comparison"]
- **Section:** [Which section/subsection]
- **Excerpt:** > "[Quote the relevant sentence or phrase directly from the paper]"
- **Problem:** [What is wrong with this, specifically. What assumption does it hide?
  What would a skeptical reader ask? Why does it weaken the paper's claim?]
- **Severity:** [Critical | Major | Minor]
- **Fix:** [Concrete action: what the authors must add, remove, or clarify]

Do NOT group findings under generic headers like "Methodology" or "Clarity."
Each finding must stand alone with its own excerpt and analysis.

# 3. Cross-Section Issues
Problems that span multiple sections (e.g., the abstract promises X but the results show Y;
the introduction frames the problem as Z but the methodology solves something else).
For each: quote from both sections and explain the contradiction or gap.
If none exist, write: "No cross-section inconsistencies detected."

# 4. Methodology Interrogation
Answer each question with a specific reference to the paper — no generic answers:
- **Research design justified?** (cite the passage where it is — or isn't — explained)
- **Dataset adequate for the claims?** (cite size, source, and any obvious gaps)
- **Evaluation metrics appropriate?** (quote which metrics are used; explain any mismatch)
- **Ablations or controls missing?** (name them concretely: "The authors test X but never
  isolate the contribution of Y, which makes it impossible to attribute the gain to Z")
- **Statistical validity?** (quote any statistical claims; flag missing confidence intervals,
  sample size justification, or p-value reporting)

# 5. Reproducibility Audit
Mark each item and add a brief note — never just a checkmark:
- [ ] Dataset: [present/partial/missing — and what specifically is lacking]
- [ ] Hyperparameters / architecture: [present/partial/missing — cite where]
- [ ] Evaluation protocol: [present/partial/missing]
- [ ] Baselines: [present/partial/missing — are they fairly implemented?]
- [ ] Code / implementation: [present/partial/missing]

# 6. Required Actions (Priority Order)
Numbered list from most to least critical. For each:
  [N]. **[Action verb + what]** — Reference: [section]. Required because: [one sentence].

# 7. Final Verdict
Recommendation: [Accept | Minor Revisions | Major Revisions | Reject]
Rationale: Two sentences grounded in the findings above. No new information here.

---

HARD CONSTRAINTS:
- Every claim you make must be traceable to a specific excerpt from the paper.
- "Findings" with no quoted text are not valid findings — rewrite them.
- Do not write generic sentences that would apply to any paper in the field.
- Do not soften critical findings with hedging language.
- Section order is fixed. Do not add or remove sections."""

    return prompt
