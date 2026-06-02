import chromadb
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_experimental.text_splitter import SemanticChunker
from pydantic import BaseModel, Field
from Promt import build_prompt

CHROMA_DIR = None

class AnalisisFragmento(BaseModel):
    contiene_metodologia: bool = Field(
        description="True si el fragmento habla sobre métodos, materiales, datos o diseño experimental. False en caso contrario."
    )
    confianza: float = Field(
        description="Nivel de certeza del análisis, de 0.0 (nada seguro) a 1.0 (totalmente seguro)."
    )

def extraer_metodologia(texto_paper: str) -> list[dict[str, any]]:
    """
    Divide un paper de forma semántica y extrae los fragmentos de metodología,
    detectando tanto títulos explícitos como secciones implícitas sin estructura.
    
    Devuelve una lista de diccionarios con el contenido y metadatos de los fragmentos.
    """
    import Interfaz as UIF

    UIF.reportar_etapa("embeddings", 0.0)
    embeds = OllamaEmbeddings(
        model='nomic-embed-text:latest',
        base_url="http://localhost:11434"
    )
    llm = ChatOllama(model="gemma3:1b", base_url="http://localhost:11434", temperature=0)
    llm_estructurado = llm.with_structured_output(AnalisisFragmento)
    UIF.reportar_etapa("embeddings", 1.0)

    UIF.reportar_etapa("chunking", 0.0)
    text_splitter = SemanticChunker(
        embeds,
        breakpoint_threshold_type="standard_deviation",
        breakpoint_threshold_amount=1.0
    )
    chunks = text_splitter.create_documents([texto_paper])
    UIF.reportar_etapa("chunking", 1.0)

    fragmentos_metodologicos = []
    total = len(chunks)

    for idx, chunk in enumerate(chunks):
        sub = (idx / total) if total else 1.0
        UIF.reportar_etapa(
            "metodologia",
            sub,
            detalle=f"Analizando fragmento {idx + 1} de {total}…",
        )

        prompt = f"""Analiza el siguiente fragmento de un artículo científico. 
        Determina si pertenece a la sección de metodología del estudio.
        
        CRITERIOS DE SELECCIÓN:
        1. RECONOCIMIENTO DIRECTO: El fragmento incluye encabezados explícitos como 'Methods', 'Methodology', 'Experimental Design', 'Materials', etc.
        2. RECONOCIMIENTO IMPLÍCITO: Si no hay títulos, el texto describe cómo se realizó la investigación (participantes, recolección de datos, software, ecuaciones, análisis estadístico, flujos de trabajo).
        
        Texto del fragmento (Índice {idx}):
        {chunk.page_content}
        """
        
        resultado = llm_estructurado.invoke(prompt)
        
        if resultado.contiene_metodologia:
            fragmentos_metodologicos.append({
                "chunk_index": idx,
                "content": chunk.page_content,
                "confidence": resultado.confianza,
                "total_chunks_evaluados": total
            })

    UIF.reportar_etapa(
        "metodologia",
        1.0,
        detalle=f"Metodología: {len(fragmentos_metodologicos)} fragmento(s) detectado(s).",
    )
    return fragmentos_metodologicos    


def _texto_para_consulta_chroma(fragmentos: list[dict], texto: str) -> str:
    if fragmentos:
        return "\n\n".join(f["content"] for f in fragmentos)
    return texto[:4000]


def completar_promt(texto: str, field_filter: str = None) -> str:
    import Interfaz as UIF

    fragmentos = extraer_metodologia(texto_paper=texto)
    query_text = _texto_para_consulta_chroma(fragmentos, texto)

    UIF.reportar_etapa("chroma", 0.0)
    cliente = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = cliente.get_collection("scipost_reviews")

    where = {"fields": {"$contains": field_filter}} if field_filter else None

    results = collection.query(
        query_texts=[query_text],
        n_results=3,
        where=where,
        include=["documents", "metadatas", "distances"]
    )
    UIF.reportar_etapa("chroma", 1.0)

    similar_reviews = [
        {
            "review_text": doc,
            "title": meta["title"],
            "journal": meta["journal"],
            "similarity": round(1 - dist, 3)
        }
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        )
    ]

    UIF.reportar_etapa("prompt", 0.0)
    aux_promt = build_prompt(texto, similar_reviews)
    UIF.reportar_etapa("prompt", 1.0)

    return aux_promt
