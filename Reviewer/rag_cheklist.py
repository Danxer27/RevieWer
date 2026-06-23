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
from pydantic import BaseModel, Field
from typing import Literal, List
from nltk.corpus import stopwords
import re

# Configuración

CONFIDENCE_THRESHOLD = 0.3   # score mínimo del keyword router antes de usar LLM fallback
N_FUSION_QUERIES     = 4     # queries generados en RAG-Fusion
RRF_K                = 60    # constante de suavizado RRF (estándar)
N_RESULTS            = 8     # chunks recuperados por query en Chroma
N_FINAL              = 5     # chunks finales tras fusión


# Keywords por tipo de estudio
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

areas = Literal[
    "rct",
    "systematic_review",
    "observational",
    "diagnostic",
    "nlp_ml",
    "case_report",
    "animal_study",
    "general",
]
keywords_instruction = "\n".join([f"- {area}: {', '.join(words)}" for area, words in ROUTES.items()])

# Routing
class FieldRouting(BaseModel):
    """Route a piece of academic paper to its most related field"""

    reasoning: str = Field(
        description="Analyze the text and closely inspect the methodology to decide which field of study it belongs to."
    )
    
    datasource: areas = Field(
        description="Choose the most relevant field of study for this paper based on the keywords found."
    )

    detected_keywords: List[str] = Field(
        description=f"Extract all the specific technical keywords found in the text that belong to the chosen area.\n"
                    f"Use these mapped keywords as a reference guide:\n{keywords_instruction}"
    )


def build_semantic_router(llm: ChatOllama):
    """
    Args:
        llm: instancia de ChatOllama (Qwen u otro modelo local)

    Returns:
        str con el study_type detectado
    """

    # Definimos el procesamiento del LLM para trabajar con el modelo de Routing establecido con BaseModel de Pydantic
    structured_llm = llm.with_structured_output(FieldRouting)

    #Prompt
    routing_prompt = ChatPromptTemplate.from_template(
    """You are an expert in research methodology and academic paper classification.

    Analyze the following paper excerpt to determine its study design, methodology, and key technical terminology. 

    Carefully evaluate the context:
    - Look for procedural words that define the architecture of the study.
    - Ensure that the keywords you identify are actively part of the study's design, and not just mentioned in passing or negated (e.g., "no placebo was used").

    Paper excerpt:
    {text}"""
    )

    router = routing_prompt | structured_llm
    route = router.invoke({"text": text})

    return route

# 2. Query Translation 
# Reformula fragmentos del paper al vocabulario formal de checklists.
# Cierra la brecha semántica: "we split data 80/20" → "dataset partitioning protocol"

_TRANSLATION_PROMPT = ChatPromptTemplate.from_template(
    """You are an expert in research reporting standards.

Rephrase the following methodology excerpt using formal checklist vocabulary.
Use terms like: eligibility criteria, allocation concealment, primary outcome,
confounding variables, blinding, dataset partitioning, evaluation protocol,
statistical analysis plan, reporting guideline.

Keep it under 80 words. Output only the rephrased text, no preamble.

Original text:
{text}

Rephrased:"""
)


def build_query_translator(llm: ChatOllama):
    """
    Retorna una chain LCEL que traduce texto de paper a vocabulario de checklist.

    Uso:
        translator = build_query_translator(llm)
        query = translator.invoke({"text": fragmento_metodologia})
    """
    return (
        _TRANSLATION_PROMPT
        | llm
        | StrOutputParser()
    ).with_config(run_name="query_translation")


# ── RAG-Fusion con RRF
# Genera N queries relacionados al fragmento del paper,
# hace retrieval con cada uno y fusiona con Reciprocal Rank Fusion.

_RAG_FUSION_PROMPT = ChatPromptTemplate.from_template(
    """You are an expert in research methodology and reporting guidelines.

Given the following methodology excerpt from a scientific paper, generate
{n_queries} different search queries to retrieve relevant items from a
reporting checklist (e.g. CONSORT, PRISMA, STROBE).

Each query should target a different aspect of the methodology
(e.g. study design, data collection, statistical analysis, outcome reporting).

Output one query per line, no numbering, no extra text.

Paper excerpt:
{text}

Queries:"""
)


def reciprocal_rank_fusion(results: list[list], k: int = RRF_K) -> list:
    """
    Fusiona múltiples listas de documentos rankeados con RRF.
    """
    fused_scores: dict[str, float] = {}

    for docs in results:
        for rank, doc in enumerate(docs):
            doc_str = dumps(doc)
            if doc_str not in fused_scores:
                fused_scores[doc_str] = 0
            fused_scores[doc_str] += 1 / (rank + k)

    reranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
    return [loads(doc_str) for doc_str, _ in reranked]


def build_rag_fusion(llm: ChatOllama, retriever):
    """
    Retorna una chain LCEL de RAG-Fusion.

    Genera N_FUSION_QUERIES queries desde el texto del paper,
    hace retrieval paralelo con cada uno y fusiona con RRF.

    Uso:
        fusion_chain = build_rag_fusion(llm, retriever)
        docs = fusion_chain.invoke({"text": fragmento, "study_type": "nlp_ml"})
    """
    generate_queries = (
        _RAG_FUSION_PROMPT
        | llm
        | StrOutputParser()
        | (lambda x: [q.strip() for q in x.split("\n") if q.strip()])
    ).with_config(run_name="rag_fusion_query_generator")

    retrieval_chain = (
        generate_queries
        | retriever.map()
        | reciprocal_rank_fusion
    ).with_config(run_name="rag_fusion_retrieval")

    return retrieval_chain


# ── Step-Back
# Abstrae el query del paper a una pregunta más general sobre diseño de estudios.
# Se usa como contexto adicional cuando el router tiene baja confianza.

_STEP_BACK_EXAMPLES = [
    {
        "input":  "We recruited 120 patients and randomly assigned them to treatment or placebo.",
        "output": "What are the key reporting requirements for randomized controlled trials?",
    },
    {
        "input":  "We trained a BERT model on the training split and evaluated on the held-out test set.",
        "output": "What are the reporting standards for machine learning experiments?",
    },
    {
        "input":  "Data were collected from hospital records between 2018 and 2022.",
        "output": "What are the reporting requirements for observational studies?",
    },
]

_step_back_example_prompt = ChatPromptTemplate.from_messages(
    [
        ("human", "{input}"),
        ("ai",    "{output}"),
    ]
)

_few_shot_step_back = FewShotChatMessagePromptTemplate(
    example_prompt=_step_back_example_prompt,
    examples=_STEP_BACK_EXAMPLES,
)

_STEP_BACK_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert in research methodology. "
            "Your task is to abstract a specific methodology excerpt into a "
            "general question about reporting standards. "
            "Here are some examples:",
        ),
        _few_shot_step_back,
        ("user", "{text}"),
    ]
)


def build_step_back(llm: ChatOllama, retriever):
    """
    Retorna una chain LCEL de Step-Back retrieval.

    Genera una pregunta abstracta sobre diseño de estudios y la usa
    como query adicional al retriever.

    Uso:
        step_back_chain = build_step_back(llm, retriever)
        docs = step_back_chain.invoke({"text": fragmento})
    """
    generate_step_back_query = (
        _STEP_BACK_PROMPT
        | llm
        | StrOutputParser()
    ).with_config(run_name="step_back_generator")

    return (
        generate_step_back_query
        | retriever
    ).with_config(run_name="step_back_retrieval")


# ChecklistRAG — integra todos los módulos 

class ChecklistRAG:
    """
    Pipeline completo de recuperación de checklists para SIRA.

    Combina:
      - Semantic Router (keywords + LLM fallback)
      - Query Translation
      - RAG-Fusion + RRF
      - Step-Back como contexto adicional cuando el router es poco confiable
    """

    def __init__(self, llm: ChatOllama, vectorstore: Chroma) -> None:
        self._llm = llm
        self._vectorstore = vectorstore
        self._router = build_semantic_router(llm)
        self._translator = build_query_translator(llm)

    def _get_retriever(self, study_type: str):
        """Retriever filtrado por study_type."""
        return self._vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": N_RESULTS,
                "filter": {"study_type": study_type},
            },
        )

    def retrieve(
        self,
        texto_paper: str,
        use_step_back: bool = False,
    ) -> list:
        """
        Pipeline completo de retrieval.

        Args:
            texto_paper:   Texto del paper (abstract + metodología recomendado).
            use_step_back: Si True, añade contexto Step-Back a los resultados.

        Returns:
            Lista de Documents rankeados por relevancia.
        """
        study_type = self._router(texto_paper)
        retriever = self._get_retriever(study_type)

        try:
            translated_query = self._translator.invoke({"text": texto_paper[:800]})
        except Exception:
            translated_query = texto_paper[:800]

        fusion_chain = build_rag_fusion(self._llm, retriever)
        docs = fusion_chain.invoke({
            "text": translated_query,
            "n_queries": N_FUSION_QUERIES,
        })

        if use_step_back:
            try:
                step_back_chain = build_step_back(self._llm, retriever)
                step_back_docs = step_back_chain.invoke({"text": texto_paper[:600]})
                seen = {dumps(d) for d in docs}
                for doc in step_back_docs:
                    if dumps(doc) not in seen:
                        docs.append(doc)
                        seen.add(dumps(doc))
            except Exception:
                pass

        if not docs:
            docs = self._vectorstore.similarity_search(
                translated_query, k=N_FINAL
            )

        return docs[:N_FINAL]

    def format_for_prompt(self, docs: list) -> str:
        """Serializa los docs recuperados para insertarlos en el prompt del LLM."""
        if not docs:
            return ""

        parts = ["<checklist_guidelines>"]
        for i, doc in enumerate(docs, 1):
            name = doc.metadata.get("checklist_name", "Checklist")
            parts.append(f"[Item {i} — {name}]")
            parts.append(doc.page_content.strip())
            if i < len(docs):
                parts.append("---")
        parts.append("</checklist_guidelines>")
        return "\n".join(parts)
