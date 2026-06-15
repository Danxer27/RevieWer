"""
prompt_engine.py — Motor de construcción de prompts para SIRA.

Responsabilidad única: transformar el texto de un paper en un prompt
listo para ser enviado al LLM revisor.

Pipeline interno:
  1. Segmentar el paper en secciones (regex → fallback párrafos).
  2. Extraer fragmentos de metodología (chunking semántico + LLM clasificador).
  3. Recuperar revisiones similares de ChromaDB (RAG).
  4. Ensamblar el prompt final con secciones + RAG + plantilla.
"""

from __future__ import annotations

import re

import chromadb
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_experimental.text_splitter import SemanticChunker
from pydantic import BaseModel, Field

import interfaz as UIF
from state import CHROMA_DIR, OLLAMA_HOST


# ---------------------------------------------------------------------------
# Esquema de salida estructurada del clasificador de metodología
# ---------------------------------------------------------------------------

class AnalisisFragmento(BaseModel):
    contiene_metodologia: bool = Field(
        description=(
            "True si el fragmento habla sobre métodos, materiales, datos "
            "o diseño experimental. False en caso contrario."
        )
    )
    confianza: float = Field(
        description="Nivel de certeza del análisis, de 0.0 (nada seguro) a 1.0 (totalmente seguro)."
    )


# ---------------------------------------------------------------------------
# Secciones esperadas en el output del LLM (para validación externa)
# ---------------------------------------------------------------------------

SECCIONES_REQUERIDAS: list[str] = [
    "# 1. Research Fingerprint",
    "# 2. Targeted Findings",
    "# 3. Cross-Section Issues",
    "# 4. Methodology Interrogation",
    "# 5. Reproducibility Audit",
    "# 6. Required Actions",
    "# 7. Final Verdict",
]


class PromptEngine:
    """
    Construye el prompt completo para la revisión de un paper académico.

    Uso típico:
        engine = PromptEngine()
        prompt = engine.completar_prompt(texto_del_paper)
    """

    # ── Patrones de segmentación por encabezados ──────────────────────────
    _SECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"(?i)^\s*abstract"), "abstract"),
        (re.compile(r"(?i)^\s*(#+\s*)?1\.?\s+introduction"), "introduction"),
        (re.compile(r"(?i)^\s*(#+\s*)?(related\s+work|background|prior\s+work|literature)"), "related_work"),
        (re.compile(r"(?i)^\s*(#+\s*)?(method|methodology|approach|proposed\s+method|our\s+method|framework)"), "methodology"),
        (re.compile(r"(?i)^\s*(#+\s*)?(experiment|result|evaluation|performance|benchmark)"), "results"),
        (re.compile(r"(?i)^\s*(#+\s*)?(discussion|analysis|ablation)"), "discussion"),
        (re.compile(r"(?i)^\s*(#+\s*)?(conclusion|future\s+work|summary)"), "conclusion"),
        (re.compile(r"(?i)^\s*(#+\s*)?(appendix|supplement)"), "appendix"),
    ]

    _MAX_SECTION_CHARS: int = 3500

    _PROMPT_CLASIFICACION: str = """\
Analiza el siguiente fragmento de un artículo científico.
Determina si pertenece a la sección de metodología del estudio.

CRITERIOS DE SELECCIÓN:
1. RECONOCIMIENTO DIRECTO: El fragmento incluye encabezados explícitos como \
'Methods', 'Methodology', 'Experimental Design', 'Materials', etc.
2. RECONOCIMIENTO IMPLÍCITO: Si no hay títulos, el texto describe cómo se realizó \
la investigación (participantes, recolección de datos, software, ecuaciones,
análisis estadístico, flujos de trabajo).

Texto del fragmento (Índice {idx}):
{contenido}
"""

    # ── Segmentación ─────────────────────────────────────────────────────

    def _detectar_etiqueta(self, linea: str) -> str | None:
        """Retorna la etiqueta de sección si la línea coincide con un patrón conocido."""
        for pattern, label in self._SECTION_PATTERNS:
            if pattern.match(linea):
                return label
        return None

    def _segmentar_paper(self, texto: str) -> dict[str, str]:
        """
        Segmenta el texto del paper en secciones etiquetadas.

        Estrategia en dos capas:
          1. Heurística rápida: regex sobre líneas que parecen encabezados.
          2. Fallback: si detecta ≤1 sección, divide por párrafos.

        Returns:
            dict[etiqueta → contenido] donde etiqueta es una de:
            abstract, introduction, related_work, methodology,
            results, discussion, conclusion, appendix, other.
        """
        lineas = texto.split("\n")
        secciones: dict[str, list[str]] = {}
        seccion_actual = "preamble"
        buffer: list[str] = []

        for linea in lineas:
            stripped = linea.strip()
            etiqueta = self._detectar_etiqueta(stripped) if stripped else None

            if etiqueta:
                if buffer:
                    secciones.setdefault(seccion_actual, []).extend(buffer)
                seccion_actual = etiqueta
                buffer = []
            else:
                buffer.append(linea)

        if buffer:
            secciones.setdefault(seccion_actual, []).extend(buffer)

        resultado: dict[str, str] = {}
        for label, lines in secciones.items():
            contenido = "\n".join(lines).strip()
            if len(contenido) < 80:
                continue
            resultado[label] = contenido[: self._MAX_SECTION_CHARS]

        if len(resultado) <= 1:
            resultado = self._segmentar_por_parrafos(texto)

        return resultado

    def _segmentar_por_parrafos(self, texto: str) -> dict[str, str]:
        """
        Fallback: divide el paper en bloques por doble salto de línea
        y los etiqueta ordinalmente. Preserva contexto aunque sin semántica
        de sección.
        """
        bloques = re.split(r"\n{2,}", texto)
        resultado: dict[str, str] = {}
        for i, bloque in enumerate(bloques):
            bloque = bloque.strip()
            if len(bloque) < 80:
                continue
            resultado[f"block_{i:03d}"] = bloque[: self._MAX_SECTION_CHARS]
        return resultado

    # ── Extracción de metodología ─────────────────────────────────────────

    def _construir_clasificador(self) -> tuple[ChatOllama, SemanticChunker]:
        """
        Inicializa embeddings y el LLM clasificador estructurado.
        Retorna (llm_estructurado, text_splitter).
        """
        UIF.reportar_etapa("embeddings", 0.0)
        embeds = OllamaEmbeddings(model="nomic-embed-text:latest", base_url=OLLAMA_HOST)
        llm = ChatOllama(model="gemma3:1b", base_url=OLLAMA_HOST, temperature=0)
        llm_estructurado = llm.with_structured_output(AnalisisFragmento)
        UIF.reportar_etapa("embeddings", 1.0)

        UIF.reportar_etapa("chunking", 0.0)
        text_splitter = SemanticChunker(
            embeds,
            breakpoint_threshold_type="standard_deviation",
            breakpoint_threshold_amount=1.0,
        )
        return llm_estructurado, text_splitter

    def _extraer_metodologia(self, texto_paper: str) -> list[dict]:
        """
        Divide el paper de forma semántica y extrae los fragmentos de metodología,
        detectando tanto títulos explícitos como secciones implícitas.

        Returns:
            Lista de dicts con content, chunk_index, confidence y total_chunks_evaluados.
        """
        llm_estructurado, text_splitter = self._construir_clasificador()
        chunks = text_splitter.create_documents([texto_paper])
        UIF.reportar_etapa("chunking", 1.0)

        fragmentos_metodologicos: list[dict] = []
        total = len(chunks)

        for idx, chunk in enumerate(chunks):
            UIF.reportar_etapa(
                "metodologia",
                (idx / total) if total else 1.0,
                detalle=f"Analizando fragmento {idx + 1} de {total}…",
            )
            prompt = self._PROMPT_CLASIFICACION.format(idx=idx, contenido=chunk.page_content)
            resultado = llm_estructurado.invoke(prompt)

            if resultado.contiene_metodologia:
                fragmentos_metodologicos.append(
                    {
                        "chunk_index": idx,
                        "content": chunk.page_content,
                        "confidence": resultado.confianza,
                        "total_chunks_evaluados": total,
                    }
                )

        UIF.reportar_etapa(
            "metodologia",
            1.0,
            detalle=f"Metodología: {len(fragmentos_metodologicos)} fragmento(s) detectado(s).",
        )
        return fragmentos_metodologicos

    # ── RAG con ChromaDB ──────────────────────────────────────────────────

    def _texto_para_query(self, fragmentos: list[dict], texto: str) -> str:
        """Usa los fragmentos de metodología como query; cae al inicio del texto si no hay."""
        if fragmentos:
            return "\n\n".join(f["content"] for f in fragmentos)
        return texto[:4000]

    def _consultar_chroma(self, query_text: str, field_filter: str | None) -> list[dict]:
        """Consulta ChromaDB y retorna las revisiones similares formateadas."""
        UIF.reportar_etapa("chroma", 0.0)

        # ── [RAG] PUNTO DE ENTRADA DE TU CADENA RAG ───────────────────────────────
        # Si tu cadena RAG vive en rag_chain.py, reemplaza el bloque de abajo con:
        #
        #   from rag_chain import MiCadenaRAG
        #   cadena = MiCadenaRAG(field_filter=field_filter)
        #   resultados = cadena.retrieve(query_text)
        #   UIF.reportar_etapa("chroma", 1.0)
        #   return resultados
        #
        # El método debe retornar una lista de dicts con las claves:
        #   { "review_text": str, "title": str, "journal": str, "similarity": float }
        # ─────────────────────────────────────────────────────────────────────────

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
        return [
            {
                "review_text": doc,
                "title": meta["title"],
                "journal": meta["journal"],
                "similarity": round(1 - dist, 3),
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    # ── Formateo del prompt ───────────────────────────────────────────────

    def _format_sections(self, sections: dict[str, str]) -> str:
        """Serializa el dict de secciones segmentadas para insertarlo en el prompt."""
        if not sections:
            return "(no section segmentation available — reason over the full text)"

        lines: list[str] = []
        for label, content in sections.items():
            lines.append(f"<section id='{label}'>")
            lines.append(content.strip())
            lines.append("</section>")
            lines.append("")
        return "\n".join(lines)

    def _format_rag(self, similar_reviews: list[dict]) -> str:
        """Formatea el bloque de contexto RAG de SciPost."""
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
            parts.append(r["review_text"][:700])
            if i < len(similar_reviews):
                parts.append("---")
        parts.append("</reference_reviews>\n")
        return "\n".join(parts)

    def _build_prompt(
        self,
        paper_text: str,
        similar_reviews: list[dict],
        sections: dict[str, str] | None = None,
    ) -> str:
        """
        Construye el prompt final para el LLM revisor.

        Args:
            paper_text:      Texto completo del paper (fallback si sections está vacío).
            similar_reviews: Reviews recuperadas de ChromaDB para calibración.
            sections:        Dict {label: contenido} con el paper segmentado por sección.
        """
        rag_block = self._format_rag(similar_reviews)
        sections_block = self._format_sections(sections or {})

        return f"""You are an expert academic peer reviewer for IEEE, Nature, and ACM journals.

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

    # ── Punto de entrada público ──────────────────────────────────────────

    def completar_prompt(self, texto: str, field_filter: str | None = None) -> str:
        """
        Construye el prompt completo para la revisión de un paper.

        Orquesta el pipeline completo:
          1. Segmentación por secciones.
          2. Extracción de fragmentos de metodología.
          3. Recuperación RAG desde ChromaDB.
          4. Ensamblado del prompt final.

        Args:
            texto:        Texto completo del paper.
            field_filter: Filtro opcional de campo para ChromaDB.

        Returns:
            Prompt listo para enviar al LLM.
        """
        # 1. Segmentación del paper en secciones
        UIF.reportar_etapa("segmentacion", 0.0)
        secciones = self._segmentar_paper(texto)
        UIF.reportar_etapa("segmentacion", 1.0)

        # 2. Extracción de metodología → construye el query para RAG
        #    [RAG] Si tu cadena necesita contexto adicional (e.g. metadatos del paper,
        #    campo de investigación, año), agrégalos aquí antes de llamar a _consultar_chroma.
        fragmentos = self._extraer_metodologia(texto)
        query_text = self._texto_para_query(fragmentos, texto)

        # 3. Recuperación RAG
        #    [RAG] _consultar_chroma es donde se conecta tu cadena. Ver comentarios allá.
        similar_reviews = self._consultar_chroma(query_text, field_filter)

        # 4. Ensamblado del prompt final
        #    [RAG] Si tu cadena genera contexto extra (e.g. definiciones, resúmenes),
        #    pásalo aquí como argumento adicional a _build_prompt.
        UIF.reportar_etapa("prompt", 0.0)
        prompt = self._build_prompt(texto, similar_reviews, sections=secciones)
        UIF.reportar_etapa("prompt", 1.0)

        return prompt
