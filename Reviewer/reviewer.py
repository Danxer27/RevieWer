# Disponible para version 3.9 - 3.14
import shutil
import Interfaz as UIF
import ollama
import threading
import fitz           # PyMuPDF
from docx import Document
from typing import Union
import re, unicodedata
from datetime import datetime
import subprocess
from pathlib import Path
from tkinter import filedialog
from Promt import promt as PROMT


cliente = ollama.Client(host='http://localhost:11434')

PDF_DIR    = Path(__file__).parent / "pdfs"
REVIEW_DIR = Path(__file__).parent / "revisiones"
TEXTOS_DIR = Path(__file__).parent / "textos"
PDF_DIR.mkdir(exist_ok=True)
REVIEW_DIR.mkdir(exist_ok=True)

MODELO_OL = None


# Estados
pdf_actual     = None
nombre_archivo = None
proceso_activo = False
stop_event     = threading.Event()
texto_actual   = None 
intento_activacion_ollama = False
#var_modelo = None
#after_display  = False


#  & "C:\Users\joel_\AppData\Local\Programs\Ollama\ollama.exe" serve  
def activar_ollama():
    # Solo en caso de que no funcione la llamada directa a ollama
    ollama_path = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    subprocess.Popen([str(ollama_path), "serve"])    

# Modelos disponibles
models = cliente.list()
modelos = []
for model in models['models']:
    modelos.append(model['model'])


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
    ruta = filedialog.askopenfilename(
        title="Seleccionar documento",
        filetypes=[("Documentos", "*.pdf *.docx")]
    )
    if not ruta:
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
    UIF.set_estado("Documento listo.", "#06d6a0")
    UIF.set_progreso(0)
    UIF.btn_iniciar.config(state="normal")

    # Limpia el txt guardado temporalmente
    texto_actual = None
    UIF.btn_procesar_texto.pack_forget()


def iniciar_revision():
    global proceso_activo, texto_actual
    if proceso_activo:
        return
    if pdf_actual is None and texto_actual is None:
        UIF.set_estado("Adjunta un documento primero.", "#e9c46a")
        return
    
    if MODELO_OL is None:
        UIF.set_estado("Debes seleciconar un modelo primero.", "#e9c46a")
        return

    stop_event.clear()
    proceso_activo = True
    UIF.btn_iniciar.config(state="disabled")
    UIF.btn_stop.config(state="normal")

    threading.Thread(target=_pipeline_hilo, daemon=True).start()


def _pipeline_hilo():
    global texto_actual
    try:
        if texto_actual is None:
            # Extraccion del texto
            UIF.set_estado("Extrayendo texto...", "#4cc9f0")
            UIF.set_progreso(5)

            if stop_event.is_set():
                return _cancelado()

            texto = extraer_texto(str(pdf_actual))
            if not texto:
                UIF.set_estado("No se pudo extraer texto.", "#e94560")
                UIF.escribir_salida("**Error:** el documento no contiene texto extraíble.")
                return _restaurar_botones()
        else:
            texto = texto_actual
        
        # Pasando a modelo para consulta
        UIF.set_estado("Consulta con modelol..", "#4cc9f0")
        UIF.set_progreso(10)

        if stop_event.is_set():
            return _cancelado()

        # Genera reporta
        reporte = revisar_paper(texto)

        if reporte is None:
            return _cancelado()

        UIF.set_estado("Guardando reporte...", "#4cc9f0")
        UIF.set_progreso(90)

        timestamp = datetime.now().strftime("%d%m%y")
        nombre_md = f"{timestamp}_{nombre_archivo}.md"
        ruta_md   = REVIEW_DIR / nombre_md
        
        # Asigna numeros a reportes repetidos
        contador = 1
        while ruta_md.exists():
            ruta_md = REVIEW_DIR / f"{nombre_md}({contador}).md"
            contador += 1
        
        with open(ruta_md, 'w', encoding='utf-8') as f:
            f.write(f"# Revisión: {nombre_archivo}\n")
            f.write(f"_Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n\n")
            f.write(reporte)

        # Si la revision se hizo desde un texto ya extraido, no vuelve a guardar el texto plano
        if texto_actual is None:
            nombre_txt = f"{timestamp}_{nombre_archivo}.txt"
            ruta_txt  = TEXTOS_DIR / nombre_txt

            with open(ruta_txt, 'w', encoding='utf-8') as f:
                f.write(texto)

            UIF._ui(UIF.cargar_textos)

        UIF._finalizar_streaming()   # render MD final limpio
        UIF.set_progreso(100)
        UIF.set_estado("Revisión completada.", "#06d6a0")
        UIF._ui(UIF.cargar_historial)
        

        if texto_actual is not None:
            texto_actual = None

    except Exception as e:
        UIF.set_estado(f"Error: {e}", "#e94560")
        UIF.escribir_salida(f"**Error inesperado:**\n\n{e}")
    finally:
        _restaurar_botones()


def revisar_paper(texto: str) -> Union[str, None]:
    global intento_activacion_ollama

    system_prompt = PROMT
    #print(system_prompt)
    UIF.set_estado("Generando revisión...", "#4cc9f0")
    UIF.set_progreso(20)
    UIF._buffer.clear()

    # Mostrar indicador de carga inicial
    UIF._ui(lambda: UIF.salida_html.load_html(UIF._md_a_html("_Generando revisión..._")))

    reporte_completo = []
    progreso_actual  = 20.0

    try:
        stream = cliente.chat(
            model=MODELO_OL,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user',   'content': f"Aquí tienes el documento para revisar:\n\n{texto}"}
            ],
            options={'num_ctx': 32000, 'temperature': 0.2},
            stream=True,
        )

        for chunk in stream:
            if stop_event.is_set():
                return None
            token = chunk['message']['content']
            reporte_completo.append(token)
            UIF.append_salida(token)
            progreso_actual = min(95.0, progreso_actual + 0.05)
            UIF.set_progreso(int(progreso_actual))

        return "".join(reporte_completo)

    except Exception as e:
        UIF.set_estado(f"Error Ollama: {e}", "#e94560")
        UIF.escribir_salida(f"**Error al comunicarse con Ollama:**\n\n{e}")
        if not intento_activacion_ollama:
            intento_activacion_ollama = True
            try:
                activar_ollama()
                return revisar_paper(texto)
            except Exception as ee:
                UIF.set_estado(f"Error al activar Ollama: {ee}", "#e94560")
                return None


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

def seleccionar_modelo(event):
    global MODELO_OL
    MODELO_OL = UIF.var_modelo.get()
    response = f"Modelo elegido: {UIF.var_modelo.get()}"
    if UIF.after_display:
        UIF.set_estado("Documento y modelos listos.", "#06d6a0")

    UIF.set_modelo_first(response, "#06d6a0")
    UIF.set_modelo_after(response, "#06d6a0")

def _ui(fn):
    UIF.root.after(0, fn)

def _restaurar_botones():
    global proceso_activo
    proceso_activo = False
    UIF.btn_iniciar.config(state="normal")
    UIF.btn_stop.config(state="disabled")

def _cancelado():
    UIF.set_estado("Proceso interrumpido.", "#e94560")
    UIF.set_progreso(0)
    UIF._buffer.clear()
    _restaurar_botones()

def interrumpir():
    if proceso_activo:
        stop_event.set()
        UIF.set_estado("Interrumpiendo...", "#e94560")



# Conexiones a comandos de la interfaz
#UIF.btn_logo.config(command=display_inicial)
UIF.btn_adjuntar_prev.config(command=adjuntar_pdf)

UIF.combo_first['values'] = modelos
UIF.combo_first.bind("<<ComboboxSelected>>", seleccionar_modelo)

UIF.btn_adjuntar.config(command=adjuntar_pdf)
UIF.btn_iniciar.config(command=iniciar_revision)
UIF.btn_stop.config(command=interrumpir)
UIF.btn_procesar_texto.config(command=iniciar_revision)

UIF.combo_after['values'] = modelos
UIF.combo_after.bind("<<ComboboxSelected>>", seleccionar_modelo)

UIF.lista_historial.bind("<<ListboxSelect>>", abrir_revision)
UIF.lista_textos.bind("<<ListboxSelect>>", abrir_texto)

UIF.REVIEW_DIR = REVIEW_DIR
UIF.TEXTOS_DIR = TEXTOS_DIR

# Cargar historial inicial
UIF.cargar_historial()
UIF.cargar_textos()
UIF.root.mainloop()
