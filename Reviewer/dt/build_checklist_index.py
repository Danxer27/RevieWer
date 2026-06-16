"""
build_checklist_index.py — Indexador de checklists para SIRA.
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_ollama import OllamaEmbeddings        
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Configuración ──────────────────────────────────────────────────────────────

RAG_DATA_DIR  = Path(__file__).resolve().parent / "rag_data_revisor"
DB_PATH       = Path(__file__).resolve().parent / "sira_chroma_db"
COLLECTION    = "checklist_guides"
EMBED_MODEL   = "nomic-embed-text:latest"                 
CHUNK_SIZE    = 600
CHUNK_OVERLAP = 120

FILE_MAP: dict[str, tuple[str, str]] = {
    "CONSORT_2025_expanded_checklist.pdf":                    ("CONSORT 2025",                 "rct"),
    "SPIRIT 2025 expanded checklist - Revised 2024Dec22.pdf": ("SPIRIT 2025",                  "rct"),
    "PRISMA_2020_expanded_checklist.pdf":                     ("PRISMA 2020",                  "systematic_review"),
    "AGREE-Reporting-Checklist.pdf":                          ("AGREE",                        "systematic_review"),
    "STROBE_checklist_v4_combined.pdf":                       ("STROBE (combined)",            "observational"),
    "STROBE_checklist_v4_cohort.pdf":                         ("STROBE (cohort)",              "cohort"),
    "STROBE_checklist_v4_case-control.pdf":                   ("STROBE (case-control)",        "case_control"),
    "STROBE_checklist_v4_cross-sectional.pdf":                ("STROBE (cross-sectional)",     "cross_sectional"),
    "CARE-checklist-English-2013.pdf":                        ("CARE 2013",                    "case_report"),
    "ARRIVE_gl_animal_research.pdf":                          ("ARRIVE guidelines",            "animal_study"),
    "Author Checklist_ARRIVE2.pdf":                           ("ARRIVE 2.0 author checklist",  "animal_study"),
    "STARD-2015-checklist.pdf":                               ("STARD 2015",                   "diagnostic"),
    "SQUIRE-2.0-checklist (1).pdf":                           ("SQUIRE 2.0",                   "quality_improvement"),
    "PIIS1098301523030310.pdf":                               ("CHEERS / HTA checklist",       "health_economics"),
    "2306.09562v1_NLP_reproducibility.pdf":                   ("NLP Reproducibility checklist","nlp_ml"),
    "2506.01789v2_Data_Rubrics.pdf":                          ("Data Rubrics for ML",          "nlp_ml"),
    "sciadv.adk3452.pdf":                                     ("Reproducibility in Science",   "nlp_ml"),
    "giae094.pdf":                                            ("Academic reporting guidelines", "general"),
    "acadmed_89_9_2014_05_22_obrien_1301196_sdc1.pdf":        ("Medical education reporting",  "general"),
}

# ── Pipeline ───────────────────────────────────────────────────────────────────

def main() -> None:
    embed_model = OllamaEmbeddings(model=EMBED_MODEL)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    # Limpiar colección existente
    vectorstore = Chroma(
        collection_name=COLLECTION,
        embedding_function=embed_model,
        persist_directory=str(DB_PATH),
    )
    vectorstore.delete_collection()
    vectorstore = Chroma(
        collection_name=COLLECTION,
        embedding_function=embed_model,
        persist_directory=str(DB_PATH),
    )

    pdfs = sorted(RAG_DATA_DIR.glob("*.pdf"))
    print(f"Encontrados {len(pdfs)} PDFs en {RAG_DATA_DIR}\n")

    total_chunks = 0
    omitidos: list[str] = []

    for pdf_path in pdfs:
        nombre = pdf_path.name

        if nombre not in FILE_MAP:
            omitidos.append(nombre)
            print(f"  [OMITIDO] {nombre}")
            continue

        checklist_name, study_type = FILE_MAP[nombre]
        print(f"  Procesando: {nombre} -> {checklist_name} ({study_type})")

        try:
            loader = PyPDFLoader(str(pdf_path))
            docs = loader.load_and_split(splitter)
        except Exception as e:
            print(f"    [ERROR] {e}")
            continue

        if not docs:
            print(f"    [ADVERTENCIA] Sin texto extraíble, omitiendo.")
            continue

        for i, doc in enumerate(docs):
            doc.metadata.update({
                "source":         nombre,
                "checklist_name": checklist_name,
                "study_type":     study_type,
                "chunk_index":    i,
                "total_chunks":   len(docs),
            })

        vectorstore.add_documents(docs)
        total_chunks += len(docs)
        print(f"    -> {len(docs)} chunks indexados")

    print(f"\nIndexación completada.")
    print(f"  Chunks totales : {total_chunks}")
    print(f"  En ChromaDB    : {vectorstore._collection.count()}")

    if omitidos:
        print(f"\nArchivos sin entrada en FILE_MAP:")
        for f in omitidos:
            print(f"    - {f}")

    # ── Verificación rápida ───────────────────────────────────────────────────
    print("\nVerificación rápida de retrieval…")
    test_queries = {
        "rct":               "randomized controlled trial allocation concealment",
        "systematic_review": "systematic review meta-analysis PRISMA",
        "nlp_ml":            "language model benchmark reproducibility dataset",
    }
    for study_type_test, query in test_queries.items():
        results = vectorstore.similarity_search(
            query,
            k=1,
            filter={"study_type": study_type_test},
        )
        if results:
            doc = results[0]
            print(f"  [{study_type_test}] -> '{doc.metadata['checklist_name']}'")
            print(f"    \"{doc.page_content[:100]}...\"")
        else:
            print(f"  [{study_type_test}] -> Sin resultados")


if __name__ == "__main__":
    main()