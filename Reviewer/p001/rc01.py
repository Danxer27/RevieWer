"""
rag_checklist.py — Módulos RAG para recuperación de checklists en SIRA.

Técnicas implementadas:
  1. Semantic Router  — keywords + fallback LLM para detectar study_type
  2. Query Translation — reformula fragmentos del paper al vocabulario del checklist
  3. RAG-Fusion + RRF — genera múltiples queries y fusiona resultados
  4. Step-Back         — abstrae el query cuando el router tiene baja confianza

Estilo: LCEL puro (chains con |), igual que prag02.ipynb.

Uso básico:
    rag = ChecklistRAG(llm=ChatOllama(...), vectorstore=Chroma(...))
    docs = rag.retrieve(texto_paper)
    context = rag.format_for_prompt(docs)
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.load import dumps, loads
from langchain_community.vectorstores import Chroma
from langchain_ollama import ChatOllama


# ── Configuración

CONFIDENCE_THRESHOLD = 0.3   # score mínimo del keyword router antes de usar LLM fallback
N_FUSION_QUERIES     = 4     # queries generados en RAG-Fusion
RRF_K                = 60    # constante de suavizado RRF (estándar)
N_RESULTS            = 8     # chunks recuperados por query en Chroma
N_FINAL              = 5     # chunks finales tras fusión

# Keywords por tipo de estudio — vocabulario diagnóstico claro
ROUTES: dict[str, list[str]] = {
    "rct": [
        "randomized", "randomised", "rct", "double-blind", "single-blind",
        "placebo", "control arm", "allocation concealment", "intention-to-treat",
        "consort", "crossover", "blinding",
    ],
    "systematic_review": [
        "systematic review", "meta-analysis", "prisma", "literature search",
        "inclusion criteria", "exclusion criteria", "forest plot",
        "heterogeneity", "grade", "prospero", "cochrane",
    ],
    "observational": [
        "cohort", "observational", "strobe", "prospective", "retrospective",
        "hazard ratio", "incidence", "longitudinal", "case-control",
        "cross-sectional", "prevalence", "odds ratio",
    ],
    "diagnostic": [
        "diagnostic accuracy", "sensitivity", "specificity", "roc curve",
        "stard", "auc", "positive predictive", "negative predictive",
        "index test", "reference standard",
    ],
    "nlp_ml": [
        "language model", "nlp", "natural language processing", "deep learning",
        "transformer", "bert", "gpt", "benchmark", "dataset split",
        "training set", "test set", "machine learning", "neural network",
        "classification", "reproducibility",
    ],
    "case_report": [
        "case report", "case series", "care guideline", "patient presentation",
        "clinical case", "individual patient",
    ],
    "animal_study": [
        "animal model", "mice", "rats", "in vivo", "arrive", "murine",
        "rodent", "preclinical", "animal experiment",
    ],
    "general": [
        "academic paper", "research article", "methodology",
    ],
}


# Semantic Router

def keyword_route(text: str) -> tuple[str, float]:
    """
    Detecta study_type por conteo de keywords en los primeros 3000 chars.
    Retorna (study_type, confidence) donde confidence = fracción de keywords hallados.
    """
    sample = text[:3000].lower()
    scores: dict[str, float] = {}

    for study_type, keywords in ROUTES.items():
        hits = sum(kw.lower() in sample for kw in keywords)
        scores[study_type] = hits / len(keywords) # fraccion normalizada

    best = max(scores, key=scores.get)
    return best, round(scores[best], 3)