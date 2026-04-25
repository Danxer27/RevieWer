# Disponible para version 3.9 - 3.14
import tkinter as tk
from tkinter import filedialog, ttk
import shutil
from pathlib import Path
import ollama
import threading
import fitz           # PyMuPDF
from docx import Document
from typing import Union
import re, unicodedata
from datetime import datetime
import markdown
from tkinterweb import HtmlFrame
import subprocess
from PIL import Image, ImageTk

cliente = ollama.Client(host='http://localhost:11434')

PDF_DIR    = Path(__file__).parent / "pdfs"
REVIEW_DIR = Path(__file__).parent / "revisiones"
TEXTOS_DIR = Path(__file__).parent / "textos"
PDF_DIR.mkdir(exist_ok=True)
REVIEW_DIR.mkdir(exist_ok=True)

MODELO_OL = "gemma3:1b"

# Modelos: llama3.2:3b, qwen3.5:4b, gemma3:1b


def activar_ollama():
    # Solo en caso de que no funcione la llamada directa a ollama
    ollama_path = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    subprocess.Popen([str(ollama_path), "serve"])    

#activar_ollama()
#  & "C:\Users\joel_\AppData\Local\Programs\Ollama\ollama.exe" serve  

# Estados
pdf_actual     = None
nombre_archivo = None
proceso_activo = False
stop_event     = threading.Event()
_buffer        = [] 
texto_actual   = None 

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

#  MARKDOWN - HTML 
def _md_a_html(texto: str) -> str:
    cuerpo = markdown.markdown(texto, extensions=["extra", "nl2br"])
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    background: #0d0d1a;
    color: #dde1e7;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 13px;
    padding: 14px 18px;
    line-height: 1.7;
    margin: 0;
  }}
  h1 {{ color: #e94560; font-size: 18px; border-bottom: 1px solid #0f3460; padding-bottom: 4px; }}
  h2 {{ color: #e94560; font-size: 15px; margin-top: 18px; }}
  h3 {{ color: #4cc9f0; font-size: 13px; margin-top: 14px; }}
  strong {{ color: #ffffff; }}
  em {{ color: #a0a0c0; }}
  code {{
    background: #0f3460;
    color: #06d6a0;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 12px;
  }}
  pre {{
    background: #0f3460;
    color: #06d6a0;
    padding: 10px;
    border-radius: 4px;
    overflow-x: auto;
  }}
  blockquote {{
    border-left: 3px solid #e94560;
    margin: 8px 0;
    padding-left: 12px;
    color: #a0a0c0;
  }}
  ul, ol {{ padding-left: 20px; }}
  li {{ margin: 3px 0; }}
  li::marker {{ color: #e94560; }}
  hr {{ border: none; border-top: 1px solid #0f3460; margin: 14px 0; }}
  p {{ margin: 6px 0; }}
</style>
</head>
<body>{cuerpo}</body>
</html>"""

# UI HELPERS 
def _ui(fn):
    root.after(0, fn)

def set_estado(texto: str, color: str = "#4a4a8a"):
    _ui(lambda: lbl_estado.config(text=texto, fg=color))

def set_progreso(valor: int):
    _ui(lambda: progress_bar.config(value=valor))

def escribir_salida(texto: str):
    #Renderiza texto como Markdown en el HtmlFrame.
    def _w():
        salida_html.load_html(_md_a_html(texto))
    _ui(_w)

def escribir_plano(texto: str):
    #Texto plano durante streaming (sin procesar MD).
    def _w():
        salida_html.load_html(_md_a_html(texto))
    _ui(_w)

def append_salida(token: str):
    #Acumula token y refresca la vista cada 40 tokens.
    _buffer.append(token)
    if len(_buffer) % 40 == 0:
        texto_hasta_ahora = "".join(_buffer)
        _ui(lambda t=texto_hasta_ahora: salida_html.load_html(_md_a_html(t)))

def _finalizar_streaming():
    #Al terminar el stream, hace el render final completo.
    texto_completo = "".join(_buffer)
    _buffer.clear()
    _ui(lambda: salida_html.load_html(_md_a_html(texto_completo)))

def _restaurar_botones():
    def _do():
        global proceso_activo
        proceso_activo = False
        btn_iniciar.config(state="normal")
        btn_stop.config(state="disabled")
    _ui(_do)


# PIPELINE DE REVISION
def adjuntar_pdf():
    global pdf_actual, nombre_archivo, texto_actual

    ruta = filedialog.askopenfilename(
        title="Seleccionar documento",
        filetypes=[("Documentos", "*.pdf *.docx")]
    )
    if not ruta:
        return

    # Copea archivo y su ruta
    src  = Path(ruta)
    dest = PDF_DIR / src.name
    shutil.copy2(src, dest)
    pdf_actual     = dest
    nombre_archivo = limpiar_nombre_archivo(src.stem)

    lbl_archivo.config(text=f"{src.name}", fg="#e94560")
    escribir_salida(f"**Documento cargado**\n\nRuta: `{dest}`\n\nPresiona ▶ Iniciar Revisión para procesar.")
    set_estado("Documento listo.", "#06d6a0")
    set_progreso(0)
    btn_iniciar.config(state="normal")

    # Limpia el txt guardado temporalmente
    texto_actual = None
    btn_procesar_texto.pack_forget()


def iniciar_revision():
    global proceso_activo, texto_actual
    if proceso_activo:
        return
    if pdf_actual is None and texto_actual is None:
        set_estado("Adjunta un documento primero.", "#e9c46a")
        return

    stop_event.clear()
    proceso_activo = True
    btn_iniciar.config(state="disabled")
    btn_stop.config(state="normal")

    threading.Thread(target=_pipeline_hilo, daemon=True).start()


def _pipeline_hilo():
    global texto_actual
    try:
        if texto_actual is None:
            # Extraccion del texto
            set_estado("Extrayendo texto...", "#4cc9f0")
            set_progreso(10)

            if stop_event.is_set():
                return _cancelado()

            texto = extraer_texto(str(pdf_actual))
            if not texto:
                set_estado("No se pudo extraer texto.", "#e94560")
                escribir_salida("**Error:** el documento no contiene texto extraíble.")
                return _restaurar_botones()
        else:
            texto = texto_actual
        
        # Pasando a modelo para consulta
        set_estado("Consulta con modelol..", "#4cc9f0")
        set_progreso(30)

        if stop_event.is_set():
            return _cancelado()

        # Genera reporta
        reporte = revisar_paper(texto)

        if reporte is None:
            return _cancelado()

        set_estado("Guardando reporte...", "#4cc9f0")
        set_progreso(90)

        timestamp = datetime.now().strftime("%d%m%y")
        nombre_md = f"{timestamp}_{nombre_archivo}.md"
        ruta_md   = REVIEW_DIR / nombre_md
        
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

            _ui(cargar_textos)

        _finalizar_streaming()   # render MD final limpio
        set_progreso(100)
        set_estado("Revisión completada.", "#06d6a0")
        _ui(cargar_historial)
        

        if texto_actual is not None:
            texto_actual = None

    except Exception as e:
        set_estado(f"Error: {e}", "#e94560")
        escribir_salida(f"**Error inesperado:**\n\n{e}")
    finally:
        _restaurar_botones()


def revisar_paper(texto: str) -> Union[str, None]:
    system_prompt = """
Eres un revisor académico experto y riguroso ("Peer Reviewer") de una revista científica de alto impacto.
Tu trabajo es leer el documento proporcionado y generar un reporte de revisión estructurado.

Debes evaluar:
1. Resumen de la contribución principal (¿Qué problema resuelve?).
2. Fortalezas del documento.
3. Debilidades o áreas de mejora (metodología, claridad, resultados).
4. Análisis exhaustivo de los procedimientos en las metodologías y experimentos.
5. Veredicto final: (Aceptar, Revisiones Menores, Revisiones Mayores, o Rechazar) con una breve justificación.

Responde en formato Markdown estructurado (usa #, ##, ###, **, listas).
Tono profesional, objetivo y constructivo. Criterios de artículo científico.
Ve al grano; escribe principalmente los puntos negativos y posibles mejorías en frases concisas.
"""
    set_estado("Generando revisión...", "#4cc9f0")
    set_progreso(50)
    _buffer.clear()

    # Mostrar indicador de carga inicial
    _ui(lambda: salida_html.load_html(_md_a_html("_Generando revisión..._")))

    reporte_completo = []
    progreso_actual  = 50.0

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
            append_salida(token)
            progreso_actual = min(88.0, progreso_actual + 0.15)
            set_progreso(int(progreso_actual))

        return "".join(reporte_completo)

    except Exception as e:
        set_estado(f"Error Ollama: {e}", "#e94560")
        escribir_salida(f"**Error al comunicarse con Ollama:**\n\n{e}")
        return None


def _cancelado():
    set_estado("Proceso interrumpido.", "#e94560")
    set_progreso(0)
    _buffer.clear()
    _restaurar_botones()


def interrumpir():
    if proceso_activo:
        stop_event.set()
        set_estado("Interrumpiendo...", "#e94560")


# Historial de reportes
def cargar_historial():
    lista_historial.delete(0, "end")
    archivos = sorted(REVIEW_DIR.glob("*.md"), reverse=True)
    if not archivos:
        lista_historial.insert("end", "  (sin revisiones)")
        return
    for f in archivos:
        lista_historial.insert("end", f"{f.stem}")

def cargar_textos():
    lista_textos.delete(0, "end")
    textos = sorted(TEXTOS_DIR.glob("*.txt"), reverse=True)
    if not textos:
        lista_textos.insert("end", "  (sin textos)")
        return
    for f in textos:
        lista_textos.insert("end", f"{f.stem}")

def abrir_revision(event):
    btn_procesar_texto.pack_forget()
    sel = lista_historial.curselection()
    if not sel:
        return
    nombre = lista_historial.get(sel[0]).strip().lstrip("").strip()
    ruta   = REVIEW_DIR / (nombre + ".md")
    if ruta.is_file():
        contenido = ruta.read_text(encoding="utf-8")
        escribir_salida(contenido)
        set_estado(f"Mostrando: {nombre[:45]}", "#06d6a0")
        
      

def abrir_texto(event):
    global texto_actual, nombre_archivo
    sel = lista_textos.curselection()
    if not sel:
        return
    nombre = lista_textos.get(sel[0]).strip().lstrip("").strip()
    ruta   = TEXTOS_DIR / (nombre + ".txt")
    if ruta.is_file():
        contenido = ruta.read_text(encoding="utf-8")
        escribir_salida(contenido)
        set_estado(f"Mostrando texto: {nombre[:45]}", "#06d6a0")
        texto_actual = contenido
        nombre_archivo = nombre  # Para usar en el procesamiento
        btn_procesar_texto.pack(side="left", padx=(8, 0))



# Interfaz grafica
root = tk.Tk()
root.title("Reviewer")
root.geometry("1200x720")
root.configure(bg="#1a1a2e")
root.resizable(True, True)


frame_main = tk.Frame(root, bg="#1a1a2e")
frame_main.pack(fill="both", expand=True)

# ── Panel izquierdo — Historial ──
frame_left = tk.Frame(frame_main, bg="#141438", width=230)
frame_left.pack(side="left", fill="y", padx=(10, 0), pady=10)
frame_left.pack_propagate(False)

_img = Image.open(Path(__file__).parent / "logo.png").resize((142, 70), Image.LANCZOS)
logo_img = ImageTk.PhotoImage(_img)

tk.Label(
    frame_left,
    image=logo_img,
    bg="#1a1a2e",
).pack(anchor="center", padx=10, pady=(12, 8))


tk.Label(
    frame_left, text="HISTORIAL",
    bg="#0f3460", fg="#a5a5ee",
    font=("Consolas", 9, "bold")
).pack(anchor="w", padx=10, pady=(12, 4))

tk.Frame(frame_left, bg="#1a1a2e", height=1).pack(fill="x", padx=8, pady=2)

frame_lista = tk.Frame(frame_left, bg="#0f3460")
frame_lista.pack(fill="both", expand=True, padx=6, pady=6)

frame_ltxt = tk.Frame(frame_left, bg="#0f3460")
frame_ltxt.pack(fill="x", expand=False, padx=6, pady=(0, 6))

# Scrolbar
style = ttk.Style()
style.theme_use("clam")
style.configure(
    "Historial.Vertical.TScrollbar",
    troughcolor="#0d0d1a",
    background="#0f3460",
    bordercolor="#0d0d1a",
    lightcolor="#0d0d1a",
    darkcolor="#0d0d1a",
    arrowcolor="#0d0d1a",
    relief="flat",
    thickness=8
)
style.map(
    "Historial.Vertical.TScrollbar",
    background=[("active", "#e94560"), ("disabled", "#0d0d1a")],
    arrowcolor=[("active", "#0d0d1a"), ("disabled", "#0d0d1a")]
)
scroll_hist = ttk.Scrollbar(frame_lista, style="Historial.Vertical.TScrollbar", orient="vertical")
scroll_hist.pack(side="right", fill="y")

lista_historial = tk.Listbox(
    frame_lista,
    bg="#0d0d1a", fg="#dde1e7",
    font=("Consolas", 12),
    relief="flat",
    selectbackground="#e94560", selectforeground="white",
    borderwidth=0, highlightthickness=0,
    yscrollcommand=scroll_hist.set,
    activestyle="none", cursor="hand2",
    selectmode="single",
)
lista_historial.pack(fill="both", expand=True)
scroll_hist.config(command=lista_historial.yview)
lista_historial.bind("<<ListboxSelect>>", abrir_revision)

tk.Button(
    frame_left, text="↻  Recargar historial",
    command=cargar_historial,
    bg="#1a1a2e", fg="#a5a5ee",
    font=("Consolas", 8), relief="flat", pady=6,
    cursor="hand2", activebackground="#0f3460", activeforeground="#dde1e7"
).pack(fill="x", padx=6, pady=(0, 8))

# ── Sección Textos ──
tk.Label(
    frame_ltxt, text="TEXTOS",
    bg="#0f3460", fg="#a5a5ee",
    font=("Consolas", 9, "bold")
).pack(anchor="w", padx=10, pady=(12, 4))

tk.Frame(frame_ltxt, bg="#1a1a2e", height=1).pack(fill="x", padx=8, pady=2)

scroll_text = ttk.Scrollbar(frame_ltxt, style="Historial.Vertical.TScrollbar", orient="vertical")
scroll_text.pack(side="right", fill="y")

lista_textos = tk.Listbox(
    frame_ltxt,
    bg="#0d0d1a", fg="#dde1e7",
    font=("Consolas", 12),
    relief="flat",
    selectbackground="#e94560", selectforeground="white",
    borderwidth=0, highlightthickness=0,
    yscrollcommand=scroll_text.set,
    activestyle="none", cursor="hand2",
    selectmode="single",
)
lista_textos.pack(fill="both", expand=True)
scroll_text.config(command=lista_textos.yview)
lista_textos.bind("<<ListboxSelect>>", abrir_texto)

tk.Button(
    frame_ltxt, text="↻  Recargar textos",
    command=cargar_textos,
    bg="#1a1a2e", fg="#a5a5ee",
    font=("Consolas", 8), relief="flat", pady=6,
    cursor="hand2", activebackground="#0f3460", activeforeground="#dde1e7"
).pack(fill="x", padx=6, pady=(0, 8))

# ── Panel derecho ──
frame_right = tk.Frame(frame_main, bg="#1a1a2e")
frame_right.pack(side="left", fill="both", expand=True, padx=10, pady=10)

# Botones
frame_btns = tk.Frame(frame_right, bg="#1a1a2e")
frame_btns.pack(fill="x", pady=(10, 6))

tk.Button(
    frame_btns, text="+  Adjuntar PDF",
    command=adjuntar_pdf,
    bg="#e94560", fg="white",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", activebackground="#c73652"
).pack(side="left", padx=(0, 8))

btn_iniciar = tk.Button(
    frame_btns, text="▶  Iniciar Revisión",
    command=iniciar_revision,
    bg="#4f7dfd", fg="#ffffff",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", activebackground="#04a87d",
    state="disabled"
)
btn_iniciar.pack(side="left", padx=(0, 8))

btn_stop = tk.Button(
    frame_btns, text="⏹  Interrumpir",
    command=interrumpir,
    bg="#a5a5ee", fg="#888",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", state="disabled",
    activebackground="#6a2040"
)
btn_stop.pack(side="left")

btn_procesar_texto = tk.Button(
    frame_btns, text="  Procesar Texto",
    command=iniciar_revision,
    bg="#06d6a0", fg="#ffffff",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", activebackground="#04a87d"
)
# Inicialmente oculto
btn_procesar_texto.pack_forget()

# Archivo seleccionado
lbl_archivo = tk.Label(
    frame_right, text="Ningún archivo seleccionado",
    bg="#1a1a2e", fg="#a5a5ee",
    font=("Consolas", 9)
)
lbl_archivo.pack(anchor="w", padx=2, pady=(0, 6))

# Barra de progreso + estado
frame_prog = tk.Frame(frame_right, bg="#1a1a2e")
frame_prog.pack(fill="x", pady=(0, 4))

# Usa el ttk.Style para scrollbar ya definido arriba
style.configure(
    "R.Horizontal.TProgressbar",
    troughcolor="#0d0d1a", background="#e94560",
    bordercolor="#0f3460", lightcolor="#4a4a8a", darkcolor="#e94560",
    thickness=8
)
progress_bar = ttk.Progressbar(
    frame_prog, orient="horizontal",
    mode="determinate", style="R.Horizontal.TProgressbar",
    maximum=100
)
progress_bar.pack(fill="x", pady=(0, 4))

lbl_estado = tk.Label(
    frame_prog, text="En espera...",
    bg="#1a1a2e", fg="#a5a5ee",
    font=("Consolas", 8), anchor="w"
)
lbl_estado.pack(fill="x")

# Separador
tk.Frame(frame_right, bg="#0f3460", height=1).pack(fill="x", pady=6)

tk.Label(
    frame_right, text="Salida / Respuesta",
    bg="#1a1a2e", fg="#a5a5ee",
    font=("Consolas", 9)
).pack(anchor="w", padx=2)

# HtmlFrame en lugar de Text
frame_text = tk.Frame(frame_right, bg="#0f3460", padx=2, pady=2)
frame_text.pack(fill="both", expand=True, pady=(4, 0))

salida_html = HtmlFrame(frame_text, horizontal_scrollbar="auto", messages_enabled=False)
salida_html.pack(fill="both", expand=True)

# Cargar historial inicial
cargar_historial()
cargar_textos()
root.mainloop()
