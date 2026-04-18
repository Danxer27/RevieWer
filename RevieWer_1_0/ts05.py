# Disponible para version 3.9 - 3.14
# Extraccion de archivos de texto plano
import tkinter as tk
from tkinter import filedialog
import shutil
from pathlib import Path
import ollama
import os
import subprocess
import fitz  # PyMuPDF
from docx import Document
from typing import Union
import re, unicodedata

#cliente = ollama
cliente = ollama.Client(host='http://localhost:11434')


# Carpeta donde se guardan los PDFs adjuntados
PDF_DIR = Path(__file__).parent / "pdfs"
PDF_DIR.mkdir(exist_ok=True)
MODELO_OL = "gemma3:1b"

pdf_actual = None
ruta_resultado = None
nombre_archivo = None

def adjuntar_pdf():
    global pdf_actual
    global ruta_resultado
    global nombre_archivo

    ruta = filedialog.askopenfilename(
        title="Seleccionar PDF",
        filetypes=[("Documentos", "*.pdf *.docx")]
    )
    if not ruta:
        return

    src = Path(ruta)
    name = Path(ruta).stem
    nombre_archivo = clean_filename(name)
    dest = PDF_DIR / src.name
    shutil.copy2(src, dest)
    pdf_actual = dest

    lbl_archivo.config(text=f"📄 {src.name}", fg="#e94560")
    salida.config(state="normal")
    salida.delete("1.0", "end")
    salida.insert("end", f"[PDF cargado]\nRuta: {dest}\n\nEsperando procesamiento...\n")
    salida.config(state="disabled")

    # Procesar pdf
    texto = extraer_texto(str(pdf_actual))
    if texto:
        revisar_paper(texto=texto, modelo=MODELO_OL)
    else:
        escribir_salida("No se pudo extraer texto del documento.")


def extraer_texto(ruta_archivo: str) -> Union[str, None]:
    """
    Extrae texto de un .pdf o .docx sin dependencias externas pesadas.
    Retorna el texto como string, o None si falla.
    """
    ruta = Path(ruta_archivo)
    
    if ruta.suffix.lower() == ".pdf":
        return _extraer_pdf(ruta)
    elif ruta.suffix.lower() == ".docx":
        return _extraer_docx(ruta)
    else:
        print(f"Formato no soportado: {ruta.suffix}")
        return None


def _extraer_pdf(ruta_pdf: Path) -> Union[str, None]:
    try:
        doc = fitz.open(str(ruta_pdf))
        texto = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        print(f"PDF extraído: {len(texto)} caracteres")
        return texto if texto.strip() else None
    except Exception as e:
        print(f"Error al leer PDF: {e}")
        return None


def _extraer_docx(ruta_docx: Path) -> Union[str, None]:
    try:
        doc = Document(str(ruta_docx))
        texto = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        print(f"DOCX extraído: {len(texto)} caracteres")
        return texto if texto.strip() else None
    except Exception as e:
        print(f"Error al leer DOCX: {e}")
        return None


def escribir_salida(texto: str):
    salida.config(state="normal")
    salida.delete("1.0", "end")
    salida.insert("end", texto)
    salida.config(state="disabled")


def revisar_paper(texto, modelo):

    texto_paper = texto

    # Configuracion del prompt del modelo
    system_prompt = """
    Eres un revisor académico experto y riguroso ("Peer Reviewer") de una revista científica de alto impacto. 
    Tu trabajo es leer el documento proporcionado y generar un reporte de revisión estructurado.
    
    Debes evaluar:
    1. Resumen de la contribución principal (¿Qué problema resuelve?).
    2. Fortalezas del documento.
    3. Debilidades o áreas de mejora (metodología, claridad, resultados).
    4. Analisis Exahustivo de los procedimientos en las metodologias y experimentos
    4. Veredicto final: (Aceptar, Revisiones Menores, Revisiones Mayores, o Rechazar) con una breve justificación.
    
    Responde estrictamente en formato legible y ordenado ya que se mostrara en una interfaz grafica de texto, y mantén un tono profesional, objetivo y constructivo.

    Califica siempre sobre criterios de un articulo cientifico.

    Para la salida no es necesario explayarse durante largos parrafos para explicar cosas buenas y malas sobre cada punto,
    ve al grano y escribe sobre todo los puntos negativos y posibles mejorias del documento en frases concisas.
    Respuestas siempre en Español.
    """

    print(f" Enviando el texto a Ollama (Modelo: {modelo})... Esto puede tardar un poco.")
    
    # Hacemos la llamada a Ollama
    try:
        respuesta = cliente.chat(
            model=modelo,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"Aquí tienes el documento para revisar:\n\n{texto_paper}"}
            ],
            # TRUCO VITAL: Aumentar el contexto para que quepa todo el paper
            # 32000 tokens suelen ser suficientes para ~30 páginas. 
            options={
                'num_ctx': 32000, 
                'temperature': 0.2 # Temperatura baja para que sea analítico y no invente cosas (alucinaciones)
            }
        )
        
        # Mostramos y guardamos el resultado
        reporte = respuesta['message']['content']
        
        # print("\n" + "="*50)
        # print(" REPORTE DE REVISIÓN")
        # print("="*50 + "\n")
        # print(reporte)f
        escribir_salida(reporte)
        
        # Guardar el reporte en un archivo
        with open("reporte_revision{}.mmd".format(nombre_archivo), 'w', encoding='utf-8') as f:
            f.write(reporte)
            
    except Exception as e:
        print(f"Error al comunicarse con Ollama: {e}")


def clean_filename(name):
    name = unicodedata.normalize('NFD', name)
    name = name.encode('ascii', 'ignore').decode()   
    name = re.sub(r'[^\w\s-]', '', name)           
    name = re.sub(r'\s+', '_', name.strip())
    return name.lower()

# ── UI ─────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("Adjuntor de PDF")
root.geometry("1024x756")
root.configure(bg="#1a1a2e")
root.resizable(False, False)

# Botón adjuntar
btn = tk.Button(
    root, text="➕  Adjuntar PDF",
    command=adjuntar_pdf,
    bg="#e94560", fg="white",
    font=("Consolas", 12, "bold"),
    relief="flat", padx=20, pady=10,
    cursor="hand2", activebackground="#c73652"
)
btn.pack(pady=(30, 10))

# Nombre del archivo cargado
lbl_archivo = tk.Label(
    root, text="Ningún archivo seleccionado",
    bg="#1a1a2e", fg="#4a4a8a",
    font=("Consolas", 10)
)
lbl_archivo.pack()

# Separador visual
tk.Frame(root, bg="#0f3460", height=1).pack(fill="x", padx=20, pady=16)

# Etiqueta de salida
tk.Label(
    root, text="Salida / Respuesta",
    bg="#1a1a2e", fg="#4a4a8a",
    font=("Consolas", 9)
).pack(anchor="w", padx=22)

# Recuadro de texto (salida)
frame_text = tk.Frame(root, bg="#0f3460", padx=2, pady=2)
frame_text.pack(fill="both", expand=True, padx=20, pady=(4, 20))

salida = tk.Text(
    frame_text,
    bg="#0d0d1a", fg="#dde1e7",
    font=("Consolas", 10),
    relief="flat", wrap="word",
    state="disabled",
    insertbackground="white",
    padx=10, pady=8
)

scrollbar = tk.Scrollbar(frame_text, command=salida.yview)
salida.config(yscrollcommand=scrollbar.set)
scrollbar.pack(side="right", fill="y")
salida.pack(fill="both", expand=True)

root.mainloop()