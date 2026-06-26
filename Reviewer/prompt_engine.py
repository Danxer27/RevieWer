"""
prompt_engine.py — Motor de construcción de prompts para SIRA (Optimizado)
"""

print("PE: ----Importando librerias---", flush=True)
#from __future__ import annotations

print("PE: Importando chroma")
import chromadb
print("PE: Importando langchain text ")
from langchain_text_splitters import RecursiveCharacterTextSplitter # DA ERROR AQUI, ERROR
print("PE: Importando pydantic ")
from pydantic import BaseModel, Field
print("PE: Importando langchain ollama ")
from langchain_ollama import ChatOllama

print("PE: Importando Cheklistrag ")
from rag_cheklist import ChecklistRAG 
print("PE: Importando interfaz ")
import interfaz as UIF
print("PE: Importando state chroma dir ")
from state import CHROMA_DIR

print("PM: definiendo AnalisisFragmento", flush=True)
class AnalisisFragmento(BaseModel):
    contiene_metodologia: bool = Field(
        description="True si el fragmento habla sobre métodos, materiales o diseño experimental."
    )
    confianza: float = Field(
        description="Nivel de certeza del análisis, de 0.0 a 1.0."
    )
print("PM: AnalisisFragmento OK", flush=True)
class PromptEngine:
    def __init__(self):
        # Usamos splitters estándar y probados de LangChain
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", " ", ""]
        )
        pass

    def _extraer_metodologia_y_contexto(self, texto_paper: str) -> str:
        """
        En lugar de usar el LLM para evaluar TODOS los chunks uno por uno (muy lento),
        usamos un enfoque de "Recuperación Híbrida/Semántica" o extraemos los primeros chunks.
        Si necesitas absoluta precisión metodológica, es mejor dejar que el LLM final
        lea todo el paper completo en el prompt. 
        
        Aquí retornamos un resumen representativo para hacer el query a ChromaDB.
        """
        UIF.reportar_etapa("procesamiento", 0.0)
        chunks = self.text_splitter.split_text(texto_paper)
        #chunks = "some text" ### PARA cuando se desactiva text_splitter
        UIF.reportar_etapa("procesamiento", 1.0)
        
        # Para consultar Chroma, tomamos muestras del inicio (Abstract/Intro) 
        # y del medio (típicamente Metodología) para formar un query fuerte sin exceder límites.
        if len(chunks) > 5:
            query_representativo = f"{chunks[0]}\n\n...\n\n{chunks[len(chunks)//2]}"
        else:
            query_representativo = texto_paper

        return query_representativo

    def _consultar_chroma(self, query_text: str, field_filter: str | None) -> list[dict]:
        """Consulta ChromaDB y retorna las revisiones similares formateadas."""
        UIF.reportar_etapa("chroma", 0.0)

        cliente = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = cliente.get_collection("scipost_reviews")
        where = {"fields": {"$contains": field_filter}} if field_filter else None
        
        results = collection.query(
            query_texts=[query_text],
            n_results=3,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        UIF.reportar_etapa("chroma", 1.0)
        
        if not results["documents"] or not results["documents"][0]:
            return []

        return [
            {
                "review_text": doc,
                "title": meta.get("title", "Unknown source") if meta else "Unknown",
                "journal": meta.get("journal", "Unknown journal") if meta else "Unknown",
                "similarity": round(1 - dist, 3),
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    def _consultar_checklists(self, query_text: str, llm: ChatOllama) -> list[dict]:
        """Recupera ítems de checklist desde el índice de checklists de SIRA."""
        UIF.reportar_etapa("checklists", 0.0)
        try:
            print("Importando CheckListRag")
            rag = ChecklistRAG(llm, CHROMA_DIR)
            print("Importado...\nHaciendo Retrieval")
            docs = rag.retrieve(query_text)
            print("Completado")
            print("Documentos:", docs)
        except Exception as e:
            UIF.reportar_etapa("checklists", 1.0)
            UIF.reportar_error(f"Error al recuperar checklists: {e}")
            return []

        UIF.reportar_etapa("checklists", 1.0)
        return [
            {
                "checklist_text": doc.page_content,
                "checklist_name": doc.metadata.get("checklist_name", "Checklist"),
                "study_type": doc.metadata.get("study_type", "general"),
            }
            for doc in docs
        ]

    def _format_rag(self, similar_reviews: list[dict]) -> str:
        if not similar_reviews: return ""
        parts = ["<reference_reviews>\nReal peer reviews from SciPost on comparable papers. Use them to calibrate tone. Do NOT copy them.\n"]
        for i, r in enumerate(similar_reviews, 1):
            parts.append(f"[Ref {i} — '{r['title']}' | {r['journal']} | sim={r['similarity']}]\n{r['review_text'][:1000]}")
            if i < len(similar_reviews): parts.append("---")
        parts.append("</reference_reviews>\n")
        return "\n".join(parts)

    def _format_checklist_guidelines(self, checklist_docs: list[dict] | None) -> str:
        if not checklist_docs: return ""
        parts = ["<checklist_guidelines>\nChecklist fragments to help identify missing details. Use as guidance.\n"]
        for i, doc in enumerate(checklist_docs, 1):
            parts.append(f"[Checklist {i} — {doc['checklist_name']} | {doc['study_type']}]\n{doc['checklist_text'][:1000]}")
            if i < len(checklist_docs): parts.append("---")
        parts.append("</checklist_guidelines>\n")
        return "\n".join(parts)

    def _build_prompt(
        self,
        paper_text: str,
        similar_reviews: list[dict],
        checklist_docs: list[dict] | None = None,
    ) -> str:
        """Construye el prompt final con el paper COMPLETO."""
        rag_block = self._format_rag(similar_reviews)
        checklist_block = self._format_checklist_guidelines(checklist_docs)

        return f"""You are an expert academic peer reviewer for IEEE, Nature, and ACM journals.

Your job is NOT to fill a scorecard. Your job is to read specific passages from this paper,
identify concrete problems, and explain exactly what is wrong and why — citing the text directly.

{rag_block}{checklist_block}
## HOW TO REASON (internal — do not output these steps)
1. Read the provided paper carefully.
2. Ask: Is there a claim here that is not justified? An assumption left unstated?
   A conclusion that does not follow from the evidence?
3. Mark it as a FINDING — copy the specific phrase, then explain the problem.

## FULL PAPER FOR REVIEW
<paper_content>
{paper_text}
</paper_content>

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

    def completar_prompt(self, texto: str, llm: ChatOllama, field_filter: str | None = None) -> str:
        """Orquesta el pipeline usando el texto completo."""
        UIF.reportar_etapa("iniciando_motor", 0.0)
        
        # 1. Extraer un query representativo para RAG sin frenar el proceso
        print("COP: Extrayendo texto")
        query_text = self._extraer_metodologia_y_contexto(texto)

        # 2. Recuperación
        print("COP: Consulta chroma para scipost")
        similar_reviews = self._consultar_chroma(query_text, field_filter)
        #checklist_docs = self._consultar_checklists(query_text, llm)
        checklist_docs = "" # REEMPLAZO PARA TESTEAR SIN RAG DE CHECKLIST

        # 3. Ensamblar prompt con el paper COMPLETO (sin truncar)
        print("COP: Ensamble")
        UIF.reportar_etapa("prompt", 0.0)
        prompt = self._build_prompt(
            texto,
            similar_reviews,
            checklist_docs=checklist_docs,
        )
        UIF.reportar_etapa("prompt", 1.0)

        return prompt
    
print("PM: PromptEngine OK", flush=True)
print("PM: módulo completo", flush=True)