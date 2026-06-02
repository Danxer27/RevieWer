
SECCIONES_REQUERIDAS = [
    "# 1. Summary",
    "# 2. Dimension Scores",
    "# 3. Strengths",
    "# 4. Weaknesses",
    "# 5. Methodology Deep Analysis",
    "# 6. Reproducibility Checklist",
    "# 7. Required Actions",
    "# 8. Final Verdict",
]

def build_prompt(paper_text: str, similar_reviews: list[dict]) -> str:
    
    # Formatear las reviews recuperadas de ChromaDB
    rag_context = ""
    if similar_reviews:
        rag_context = "<reference_reviews>\n"
        rag_context += "The following are real peer reviews from SciPost on similar papers. "
        rag_context += "Use them as calibration reference for tone, depth, and criteria — "
        rag_context += "do NOT copy them, do NOT mention them in your output.\n\n"
        
        for i, r in enumerate(similar_reviews, 1):
            rag_context += f"[Reference Review {i} — '{r['title']}' | "
            rag_context += f"Journal: {r['journal']} | "
            rag_context += f"Similarity: {r['similarity']}]\n"
            rag_context += f"{r['review_text'][:800]}\n"  # truncar para no explotar el contexto
            rag_context += "</reference_reviews>\n\n" if i == len(similar_reviews) else "\n---\n"
        
        if not rag_context.endswith("</reference_reviews>\n\n"):
            rag_context += "</reference_reviews>\n\n"

    prompt = f"""You are a strict academic peer reviewer for IEEE/Nature/ACM journals.

## INTERNAL REASONING PROTOCOL (follow silently before writing)
Before writing your review, complete these steps mentally:
STEP 1: Identify the core research question in one sentence.
STEP 2: Identify the methodology used (algorithm, dataset, evaluation metric).
STEP 3: Check each section: Abstract, Introduction, Related Work, Methodology, Results, Conclusion.
STEP 4: For each of the 4 dimensions below, assign a score using the rubric.
STEP 5: Derive the final verdict from the average score.

## SCORING RUBRIC (use this for every dimension)
Score 5 — Exceptional. No significant issues. Ready for publication.
Score 4 — Good. Minor gaps that do not threaten validity.
Score 3 — Acceptable. Significant gaps that must be addressed.
Score 2 — Weak. Fundamental issues that likely require major rework.
Score 1 — Unacceptable. Missing or critically flawed. Grounds for rejection.

{rag_context}<paper_to_review>
{paper_text}
</paper_to_review>

## OUTPUT FORMAT (follow this structure exactly, in this order)

# 1. Summary
- Research question (1 sentence):
- Proposed solution (1 sentence):
- Why it matters (1 sentence):

# 2. Dimension Scores
| Dimension       | Score (1-5) | One-line justification |
|-----------------|-------------|------------------------|
| Novelty         |             |                        |
| Methodology     |             |                        |
| Reproducibility |             |                        |
| Clarity         |             |                        |
| **Average**     |             |                        |

# 3. Strengths
For each strength: state the specific section/element and why it is strong.
Minimum 2, maximum 5. No generic praise.

# 4. Weaknesses (CRITICAL)
For each weakness:
- [SEVERITY: High/Medium/Low] Description of the issue.
- Specific section or claim where it occurs.
- Concrete action required to fix it.
Minimum 3 weaknesses. Do not soften.

# 5. Methodology Deep Analysis
- Are methods justified? (Yes/Partial/No) — explain.
- Are experiments sufficient? (Yes/Partial/No) — explain.
- Missing ablations or controls: list them.
- Statistical validity: (Yes/Partial/No) — explain.

# 6. Reproducibility Checklist
For each item, mark [✓] present, [✗] missing, [~] partial:
- [ ] Dataset description and access
- [ ] Hyperparameters and architecture details
- [ ] Evaluation metrics defined
- [ ] Baseline comparisons
- [ ] Code or implementation details

# 7. Required Actions (Priority Order)
List actions the authors MUST take, numbered from most to least critical.
Each action must reference a specific section and propose a concrete fix.

# 8. Final Verdict
Score average: [X.X]
Verdict: [Accept / Minor Revisions / Major Revisions / Reject]
Justification (2 sentences max, based on the scores above):

---
CONSTRAINTS:
- Do NOT add sections not listed above.
- Do NOT change the order of sections.
- The table in section 2 must always be present and fully filled.
- Severity tags [High/Medium/Low] are mandatory in section 4.
- Do NOT write generic comments. Every claim must reference a specific part of the paper."""

    return prompt