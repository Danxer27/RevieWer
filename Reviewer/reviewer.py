# Disponible para version 3.11
import shutil
import Interfaz as UIF
import ollama
import threading
try:
    import pymupdf as fitz
except ImportError:
    import fitz           # PyMuPDF
from docx import Document
from typing import Union
import re, unicodedata
from datetime import datetime
from pathlib import Path
#from Promt import promt as PROMT
from Promt import SECCIONES_REQUERIDAS
import numpy as np
from modeling import revisar_paper
import Construir_promt



cliente = ollama.Client(host='http://localhost:11434')

PDF_DIR    = Path(__file__).parent / "pdfs"
REVIEW_DIR = Path(__file__).parent / "revisiones"
TEXTOS_DIR = Path(__file__).parent / "textos"
CHROMA_DIR = Path(__file__).parent / "dt/sira_chroma_db"
PDF_DIR.mkdir(exist_ok=True)
REVIEW_DIR.mkdir(exist_ok=True)
TEXTOS_DIR.mkdir(exist_ok=True)

MODELO_OL = None


# Estados
pdf_actual     = None
nombre_archivo = None
proceso_activo = False
stop_event     = threading.Event()
texto_actual   = None 
#intento_activacion_ollama = False
#var_modelo = None
#after_display  = False   

# Modelos disponibles
models = cliente.list()
modelos = []
for model in models['models']:
    modelos.append(model['model'])

Color_alerta = {
    'rojo':'#e94560',
    'amarillo':'#e9c46a',
    'verde':'#06d6a0',
    'azul':'#4cc9f0'
}

Construir_promt.CHROMA_DIR = CHROMA_DIR

# Helpers para texto
def limpiar_nombre_archivo(name: str) -> str:
    name = unicodedata.normalize('NFD', name)
    name = name.encode('ascii', 'ignore').decode()
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name.lower()


def extraer_texto(ruta_archivo: str) -> Union[str, None]:
    ruta = Path(ruta_archivo)
    if ruta.suffix.lower() == ".pdf":
        try:
            doc = fitz.open(str(ruta_archivo))
            texto = "\n\n".join(page.get_text() for page in doc)
            doc.close()
            return texto if texto.strip() else None
        except Exception as e:
            print(f"Error al leer el pdf: (e)")
            return None

    elif ruta.suffix.lower() == ".docx":
        try:
            doc = Document(str(ruta_archivo))
            texto = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return texto if texto.strip() else None
        except Exception as e:
            print(f"Error al leer DOCX: {e}")
    print(f"Formato no soportado: {ruta.suffix}")
    return None 



# PIPELINE DE REVISION
def adjuntar_pdf():
    global pdf_actual, nombre_archivo, texto_actual
    ruta = UIF.ask_open_file(
        "Seleccionar documento",
        "Documentos (*.pdf *.docx);;Todos los archivos (*.*)",
    )
    if not ruta:
        UIF.set_estado("Error al establecer la ruta del documento.", )
        return

    
    UIF.iniciar_display_derecho()

    # Copea archivo y su ruta
    src  = Path(ruta)
    dest = PDF_DIR / src.name
    shutil.copy2(src, dest)
    pdf_actual     = dest
    nombre_archivo = limpiar_nombre_archivo(src.stem)

    UIF.lbl_archivo.config(text=f"{src.name}", fg="#e94560")
    UIF.escribir_salida(f"**Documento cargado**\n\nRuta: `{dest}`\n\nPresiona ▶ Iniciar Revisión para procesar.")
    UIF.reportar_etapa("preparado", 1.0)
    UIF.set_progreso(0)
    UIF.btn_iniciar.config(state="normal")

    # Limpia el txt guardado temporalmente
    texto_actual = None
    UIF.btn_procesar_texto.pack_forget()


# def extraer_metodologia(texto: str):

#     embeds = OllamaEmbeddings(
#         model='nomic-embed-text:latest',
#         base_url="http://localhost:11434"
#     )

#     txt_splitter = SemanticChunker(
#         embeds,
#         breakpoint_threshold_type="standar_deviation", 
#         breakpoint_threshold_amount=1.25, 
#     )

#     paper_text = texto
#     chunks = txt_splitter.create_document([paper_text])

#     keywords_metodologia = [
#     "experimental design", "materials and methods", "data collection", 
#     "participants", "statistical analysis", "procedures", "framework",
#     ]

#     query_embed = embeds.embed_query(" ".join(keywords_metodologia))

#     metodologia_chunks = []
#     umbral_similitud = 0.5

#     for idx, chunk in enumerate(chunks):
#         chunk_embed = embeds.embed_documents(chunk.page_context)

#         #Calcular similutd
#         simil = np.dot(query_embed, chunk_embed) / (
#             np.linalg.norm(query_embed) * np.linalg.norm(chunk_embed)
#         )

#         if simil > umbral_similitud:
#             metodologia_chunks.append((simil, chunk.page_content))


def iniciar_revision():
    global proceso_activo, texto_actual
    if proceso_activo:
        UIF.reportar_etapa("advertencia", 0.0, detalle="Proceso en curso; espera a que termine.")
        return
    if pdf_actual is None and texto_actual is None:
        UIF.reportar_etapa("advertencia", 0.0, detalle="Adjunta un documento primero.")
        return

    if MODELO_OL is None:
        UIF.reportar_etapa("advertencia", 0.0, detalle="Selecciona un modelo primero.")
        return

    stop_event.clear()
    proceso_activo = True
    UIF.btn_iniciar.config(state="disabled")
    UIF.btn_stop.config(state="normal")
    UIF.reportar_etapa("iniciando", 0.0)

    threading.Thread(target=_pipeline_hilo, daemon=True).start()


def _pipeline_hilo():
    global texto_actual, proceso_activo
    try:
        if texto_actual is None:
            UIF.reportar_etapa("extraccion_texto", 0.0)

            if stop_event.is_set():
                proceso_activo = False
                return _cancelado()

            texto = extraer_texto(str(pdf_actual))
            if not texto:
                UIF.reportar_error("No se pudo extraer texto del documento.")
                UIF.escribir_salida("**Error:** el documento no contiene texto extraíble.")
                return
            UIF.reportar_etapa("extraccion_texto", 1.0)
        else:
            texto = texto_actual
            UIF.reportar_etapa("extraccion_texto", 1.0)

        if stop_event.is_set():
            proceso_activo = False
            return _cancelado()

        # Genera reporta
        reporte = revisar_paper(texto, MODELO_OL)

        if reporte is None:
            return _cancelado()
        
        # Validar estructura
        es_valido, faltantes = validar_reporte(reporte)
        if not es_valido:
            UIF.reportar_etapa(
                "advertencia",
                0.5,
                detalle=f"Reporte incompleto: faltan {', '.join(faltantes)}",
            )
            advertencia = f"\n\n---\n **Secciones no generadas:** {', '.join(faltantes)}"
            reporte += advertencia

        UIF.reportar_etapa("guardando", 0.0)

        #timestamp = datetime.now().strftime("%d%m%y")
        nombre_md = f"{nombre_archivo}.md"
        ruta_md   = REVIEW_DIR / nombre_md
        
        # Asigna numeros a reportes repetidos
        contador = 1
        while ruta_md.exists():
            ruta_md = REVIEW_DIR / f"{nombre_md}({contador}).md"
            contador += 1
        
        with open(ruta_md, 'w', encoding='utf-8') as f:
            f.write(f"# Revisión: {nombre_archivo}\n")
            f.write(f"_Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n")
            f.write(f"_Modelo: {MODELO_OL}_\n\n")
            f.write(reporte)

        # Si la revision se hizo desde un texto ya extraido, no vuelve a guardar el texto plano
        if texto_actual is None:
            nombre_txt = f"{nombre_archivo}.txt"
            ruta_txt  = TEXTOS_DIR / nombre_txt

            with open(ruta_txt, 'w', encoding='utf-8') as f:
                f.write(texto)

            UIF._ui(UIF.cargar_textos)

        UIF._finalizar_streaming()   # render MD final limpio
        UIF.reportar_etapa("guardando", 1.0)
        UIF.reportar_etapa("completado", 1.0)
        UIF._ui(UIF.cargar_historial)
        

        if texto_actual is not None:
            texto_actual = None

    except Exception as e:
        UIF.reportar_error(str(e))
        UIF.escribir_salida(f"**Error inesperado:**\n\n{e}")
        proceso_activo = False
    finally:
        _restaurar_botones()





def validar_reporte(reporte: str) -> tuple[bool, list[str]]:
    """
    Verifica que el reporte contenga todas las secciones requeridas.
    Retorna (es_valido, secciones_faltantes).
    """
    faltantes = [s for s in SECCIONES_REQUERIDAS if s not in reporte]
    return len(faltantes) == 0, faltantes


def abrir_revision(event):
    UIF.btn_procesar_texto.pack_forget()
    UIF.iniciar_display_derecho()
    sel = UIF.lista_historial.curselection()
    if not sel:
        return
    nombre = UIF.lista_historial.get(sel[0]).strip().lstrip("").strip()
    ruta   = REVIEW_DIR / (nombre + ".md")
    if ruta.is_file():
        contenido = ruta.read_text(encoding="utf-8")
        UIF.escribir_salida(contenido)
        UIF.set_estado(f"Mostrando: {nombre[:45]}", "#06d6a0")

def abrir_texto(event):
    global texto_actual, nombre_archivo
    UIF.iniciar_display_derecho()
    sel = UIF.lista_textos.curselection()
    if not sel:
        return
    nombre = UIF.lista_textos.get(sel[0]).strip().lstrip("").strip()
    ruta   = TEXTOS_DIR / (nombre + ".txt")
    if ruta.is_file():
        contenido = ruta.read_text(encoding="utf-8")
        UIF.escribir_salida(contenido)
        UIF.set_estado(f"Mostrando texto: {nombre[:45]}", "#06d6a0")
        texto_actual = contenido
        nombre_archivo = nombre  # Para usar en el procesamiento
        UIF.btn_procesar_texto.pack(side="left", padx=(8, 0))

def seleccionar_modelo(event=None):
    global MODELO_OL
    nombre = UIF.var_modelo.get()
    if not nombre:
        return
    MODELO_OL = nombre
    response = f"Modelo elegido: {nombre}"
    if UIF.after_display and (pdf_actual is not None or texto_actual is not None):
        UIF.reportar_etapa("preparado", 1.0)
        UIF.btn_iniciar.config(state="normal")

    UIF.set_modelo_first(response, Color_alerta["verde"])
    UIF.set_modelo_after(response, Color_alerta["verde"])

def _ui(fn):
    UIF.root.after(0, fn)

def _restaurar_botones():
    global proceso_activo
    proceso_activo = False

    def _do():
        UIF.btn_iniciar.config(state="normal")
        UIF.btn_stop.config(state="disabled")

    UIF._ui(_do)

def _cancelado():
    UIF.reportar_error("Proceso interrumpido.")
    UIF._buffer.clear()
    _restaurar_botones()

def interrumpir():
    if proceso_activo:
        stop_event.set()
        UIF.reportar_etapa("error", 0.0, detalle="Interrumpiendo proceso…")



# Conexiones a comandos de la interfaz
UIF.wire_commands(
    on_adjuntar=adjuntar_pdf,
    on_iniciar=iniciar_revision,
    on_stop=interrumpir,
    on_procesar_texto=iniciar_revision,
)

UIF.combo_first['values'] = modelos
UIF.combo_after['values'] = modelos
if modelos:
    UIF.var_modelo.set(modelos[0])
    seleccionar_modelo()

UIF.combo_first.bind("<<ComboboxSelected>>", seleccionar_modelo)
UIF.combo_after.bind("<<ComboboxSelected>>", seleccionar_modelo)

UIF.lista_historial.bind("<<ListboxSelect>>", abrir_revision)
UIF.lista_textos.bind("<<ListboxSelect>>", abrir_texto)

UIF.REVIEW_DIR = REVIEW_DIR
UIF.TEXTOS_DIR = TEXTOS_DIR

# Cargar historial inicial
UIF.cargar_historial()
UIF.cargar_textos()
UIF.root.mainloop()
