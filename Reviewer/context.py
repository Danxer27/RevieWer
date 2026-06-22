import requests
import re
from typing import Union

BASE_URL = "https://api.openalex.org"

def extraer_keywords(texto: str)->list[str]:
    #Modo 1: buscar keywords
    match = re.search(
        r'(?:Index Terms|Keywords|Key words)[\s\u2002:—\-]+(.+?)(?:\n\n|\n\d+[\.\s]|\Z)',
        texto[:5000],
        re.IGNORECASE | re.DOTALL
    )
    if match:
        bloque = match.group(1).strip()
        keywords = re.split(r'[,;·\n]+', bloque)
        keywords = [k.strip() for k in keywords if k.strip()]
        keywords = [k for k in keywords if 3 < len(k) < 50]
        if keywords:
            return keywords[:6]
    
    #Modo 2: Extraer el abstract
    match = re.search(
        r'Abstract[\s\n]+(.+?)(?:\nKeywords|\n\d+[\.\s]+\w|\n\n\n)',
        texto[:5000],
        re.IGNORECASE | re.DOTALL
    )
    
    if match:
        abstract = match.group(1).strip()
        keywords = _frecuencia(abstract)
        if keywords:
            return keywords
        
    #Modo 3: Frecuencia sobre el inicio del documento
    return _frecuencia(texto[:3000])

def _frecuencia(texto: str)->list[str]:
    #Extraer las palabras más frecuentes
    STOPWORDS = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
        'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were',
        'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
        'would', 'could', 'should', 'may', 'might', 'this', 'that', 'these',
        'those', 'it', 'its', 'they', 'their', 'we', 'our', 'how', 'whether',
        'both', 'not', 'also', 'as', 'than', 'more', 'such', 'into', 'through',
        'between', 'about', 'while', 'during', 'which', 'who', 'what', 'when',
        'study', 'paper', 'research', 'results', 'data', 'using', 'used',
        'based', 'approach', 'method', 'methods', 'proposed', 'show', 'shows',
        'present', 'provide', 'provides', 'work', 'thus', 'well', 'here',
        'each', 'where', 'system', 'systems', 'however', 'further', 'can',
        'been', 'other', 'only', 'then', 'than', 'over', 'after', 'under'
    }
    palabras = re.findall(r'\b[a-z]{4,}\b', texto.lower())
    frecuencia = {}
    for p in palabras:
        if p not in STOPWORDS:
            frecuencia[p] = frecuencia.get(p, 0) + 1
    return sorted(frecuencia, key=frecuencia.get, reverse=True)[:6]
        

def buscar_papers(keywords: list[str], year_min=2020, n=8) -> list[dict]:
    if not keywords:
        return[]
    
    query = " ".join(keywords[:2])
    print(f"Query enviada: {query}")  # para verificar

    
    try:
        respuesta = requests.get(
            f"{BASE_URL}/works",
            params={
                "search": query,
                "filter": f"publication_year:>{year_min},type:article",
                "per_page": n,
                "select": "title,abstract_inverted_index,publication_year,cited_by_count,authorships,primary_location"
            },
            headers={"User-Agent": "RevieWer/1.0 (mailto:joel.estrada3620@alumnos.udg.mx)"},
            timeout=10
        )
        return respuesta.json().get("results", [])
    except Exception as e:
        print(f"Error OpenAlex: {e}")
        return []
    
def reconstruir_abstract(inverted_index: dict)->str:
    if not inverted_index:
        return "N/A"
    
    palabras = {}
    for palabra, posiciones in inverted_index.items():
        for pos in posiciones:
            palabras[pos] = palabra
    return " ".join(palabras[i] for i in sorted(palabras.keys()))[:300]

def formatear_contexto(papers: list[dict])->str:
    if not papers:
        return "No related papers found in OpenAlex."
    
    contexto = f"State of the art -{len(papers)} related papers found (2020-present): \n\n"
    
    for i, p in enumerate(papers, 1):
        
        autores = ", ".join(
            a["author"]["display_name"]
            for a in p.get("authorships", [])[:3]
            if a.get("author")
        )
        
        venue = ""
        loc = p.get("primary_location", {})
        if loc and loc.get("source"):
            venue = loc["source"].get("display_name", "")
            
        abstract = reconstruir_abstract(p.get("abstract_inverted_index"))
        
        contexto += f"""[{i}] {p.get('title', 'N/A')}
   Authors: {autores}
   Year: {p.get('publication_year', 'N/A')} | Citations: {p.get('cited_by_count', 0)}
   Venue: {venue}
   Abstract: {abstract}...

"""
    return contexto

def obtener_contexto(texto: str)-> str:
    
    # Debug: ver las primeras 2000 chars del texto extraído
    print("=== INICIO DEL TEXTO EXTRAÍDO ===")
    print(texto[:2000])
    print("=== FIN ===")
    
    print("=== SECCIÓN 1500-3500 ===")  # ← agrega esto
    print(texto[1500:3500])             # ← y esto
    print("=== FIN SECCIÓN ===")        # 
    
    keywords = extraer_keywords(texto)
    print(f"Keywords extraídas: {keywords}")
    
    if not keywords:
        return ""
    
    papers = buscar_papers(keywords)
    print(f"Papers encontrados: {len(papers)}")
    
    contexto = formatear_contexto(papers)
    return contexto[:6000] if contexto else ""