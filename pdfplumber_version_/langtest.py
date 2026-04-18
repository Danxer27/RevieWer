from langchain_ollama import OllamaLLM
from langchain_text_splitters import RecursiveCharacterTextSplitter
import pdfplumber

llm = OllamaLLM(model="mistral")

def _objeto_en_bbox(obj, bbox):
    x0, top, x1, bottom = bbox
    obj_x0 = obj.get("x0", 0)
    obj_top = obj.get("top", 0)
    return (obj_x0 >= x0 and obj_x0 <= x1 and
            obj_top >= top and obj_top <= bottom)

def extraer_texto_limpio(ruta_pdf: str) -> str:
    texto_pdf = []
    with pdfplumber.open(ruta_pdf) as pdf:
        for i, page in enumerate(pdf.pages):
            bboxes_imagenes = [
                (img["x0"], img["top"], img["x1"], img["bottom"])
                for img in page.images
            ]

            if bboxes_imagenes:
                pagina_filtrada = page
                for bbox in bboxes_imagenes:
                    pagina_filtrada = pagina_filtrada.filter(
                        lambda obj, b=bbox: not _objeto_en_bbox(obj, b)
                    )
                texto = pagina_filtrada.extract_text()
            else:
                texto = page.extract_text()

            if texto and texto.strip():
                texto_pdf.append(f"[Página {i+1}]\n{texto.strip()}")

    return "\n\n".join(texto_pdf)


texto_crudo = extraer_texto_limpio("quantum.pdf")

if not texto_crudo.strip():
    print("⚠️  No se pudo extraer texto. El PDF puede ser un escaneo.")
    exit()

with open("quantum_texto.txt", "w", encoding="utf-8") as f:
    f.write(texto_crudo)
print("📄 Texto guardado en quantum_texto.txt\n")

print(f"Texto extraído: {len(texto_crudo)} caracteres\n")

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1500,
    chunk_overlap=200,
    separators=["\n\n", "\n", ". ", " ", ""]
)

chunks = text_splitter.create_documents([texto_crudo])
chunks_validos = [c for c in chunks if len(c.page_content.strip()) > 100]

print(f"Total de fragmentos válidos: {len(chunks_validos)}\n")

for i, chunk in enumerate(chunks_validos):
    print(f"\n{'='*60}")
    print(f"  Fragmento {i+1}/{len(chunks_validos)}")
    print(f"{'='*60}\n")
    response = llm.invoke(
        "Actúa como revisor científico experto. Analiza críticamente este "
        "fragmento de paper: identifica la idea principal, evalúa el rigor "
        "metodológico si aplica, y señala fortalezas o debilidades.\n\n"
        + chunk.page_content
    )
    print(response)