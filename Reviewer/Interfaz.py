import tkinter as tk
from tkinter import filedialog, ttk
from PIL import Image, ImageTk
from pathlib import Path
from tkinterweb import HtmlFrame
import markdown

_buffer = [] 
after_display = False
REVIEW_DIR = None
TEXTOS_DIR = None


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

def set_modelo_first(texto: str, color: str = "#4a4a8a"):
    _ui(lambda: lbl_text_first_model.config(text=texto, fg=color))

def set_modelo_after(texto: str, color: str = "#4a4a8a"):
    _ui(lambda: lbl_text_model_mini.config(text=texto, fg=color))

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
        btn_iniciar.config(state="normal")
        btn_stop.config(state="disabled")
    _ui(_do)



# Funciones
def _cancelado():
    set_estado("Proceso interrumpido.", "#e94560")
    set_progreso(0)
    _buffer.clear()
    _restaurar_botones()

def interrumpir():
    set_estado("Interrumpiendo...", "#e94560")

def display_inicial():
    frame_right.pack_forget()
    frame_right_first.pack()

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



# Interfaz grafica
root = tk.Tk()
root.title("Reviewer")
root.geometry("1200x720")
root.configure(bg="#1a1a2e")
root.resizable(True, True)


frame_main = tk.Frame(root, bg="#1a1a2e")
frame_main.pack(fill="both", expand=True)

#  Panel izquierdo — Historial
frame_left = tk.Frame(frame_main, bg="#141438", width=230)
frame_left.pack(side="left", fill="y", padx=(10, 0), pady=10)
frame_left.pack_propagate(False)

_img = Image.open(Path(__file__).parent / "imgs/logo.png").resize((142, 70), Image.LANCZOS)
logo_img = ImageTk.PhotoImage(_img)

btn_logo = tk.Button(
    frame_left,
    image=logo_img,
    bg="#1a1a2e",
    command=display_inicial
)
btn_logo.pack(anchor="center", padx=10, pady=(12, 8))


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

# tk.Button(
#     frame_left, text="↻  Recargar historial",
#     command=cargar_historial,
#     bg="#1a1a2e", fg="#a5a5ee",
#     font=("Consolas", 8), relief="flat", pady=6,
#     cursor="hand2", activebackground="#0f3460", activeforeground="#dde1e7"
# ).pack(fill="x", padx=6, pady=(0, 8))

#Sección Textos
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

# tk.Button(
#     frame_ltxt, text="↻  Recargar textos",
#     command=cargar_textos,
#     bg="#1a1a2e", fg="#a5a5ee",
#     font=("Consolas", 8), relief="flat", pady=6,
#     cursor="hand2", activebackground="#0f3460", activeforeground="#dde1e7"
# ).pack(fill="x", padx=6, pady=(0, 8))



# ── Panel derecho ──
frame_right = tk.Frame(frame_main, bg="#1a1a2e")
frame_right.pack(side="left", fill="both", expand=True, padx=10, pady=10)
frame_right.pack_forget()

frame_right_first = tk.Frame(frame_main, bg="#1a1a2e")
frame_right_first.pack(side="left", fill="both", expand=True, padx=10, pady=10)



    # Panel derecho al inicio
img_f = Image.open(Path(__file__).parent / "imgs/logo.png").resize((355, 175), Image.LANCZOS)
logo_imgf = ImageTk.PhotoImage(img_f)
tk.Label(
    frame_right_first,
    image=logo_imgf,
    bg="#1a1a2e",
).pack(pady=(200, 50), padx=8, side="top", anchor="center")

lbl_title = tk.Label(
    frame_right_first, text="RevieWer",
    bg="#1a1a2e" , fg="#c73652",
    font=("Consolas", 32, "bold")
).pack(pady=(8, 8), padx=8, side="top", anchor="center")

lbl_text_first = tk.Label(
    frame_right_first, text="Adjunta tu documento",
    bg="#1a1a2e",fg="#a5a5ee",
    font=("Consolas", 12, "bold")
)
lbl_text_first.pack(pady=(0, 8), padx=8, side="top", anchor="center")

btn_adjuntar_prev = tk.Button(
    frame_right_first, text="+  Adjuntar PDF",
    command=None,
    bg="#e94560", fg="white",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", activebackground="#c73652"
)
btn_adjuntar_prev.pack(pady=(50, 8), padx=8, side="top", anchor="center")

lbl_text_first_model = tk.Label(
    frame_right_first, text="Selecciona un modelo",
    bg="#1a1a2e",fg="#a5a5ee",
    font=("Consolas", 12, "bold")
)
lbl_text_first_model.pack(pady=(0, 8), padx=8, side="top", anchor="center")

    # Seleccion de modelo mediante listbox
# style.configure(
#     "TCombobox*Listbox",
#     fieldbackground="#0d0d1a",
#     background="#0f3460",
#     foreground="white",
#     arrowcolor="#e94560",
#     padding=5
# )

# style.map(
#     "TCombobox*Listbox",
#     fieldbackground=[("readonly", "#0d0d1a")],
#     background=[("active", "#e94560"), ("disabled", "#0d0d1a")],
#     arrowcolor=[("active", "white"), ("disabled", "#0d0d1a")]
# )
var_modelo = tk.StringVar()
combo_first = ttk.Combobox(frame_right_first, textvariable=var_modelo, state="readonly")
combo_first['values'] = []
combo_first.pack()

root.option_add("*TCombobox*Listbox.background", "#0d0d1a")
root.option_add("*TCombobox*Listbox.foreground", "white")
root.option_add("*TCombobox*Listbox.selectBackground", "#e94560")
root.option_add("*TCombobox*Listbox.selectForeground", "#0f3460")


def iniciar_display_derecho():
    global after_display
    frame_right_first.pack_forget()
    frame_right.pack(side="left", fill="both", expand=True, padx=10, pady=10)
    after_display = True

# Botones
frame_btns = tk.Frame(frame_right, bg="#1a1a2e")
frame_btns.pack(fill="x", pady=(10, 6))

btn_adjuntar = tk.Button(
    frame_btns, text="+  Adjuntar PDF",
    command=None,
    bg="#e94560", fg="white",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", activebackground="#c73652"
)
btn_adjuntar.pack(side="left", padx=(0, 8))


btn_iniciar = tk.Button(
    frame_btns, text="▶  Iniciar Revisión",
    command=None,
    bg="#4f7dfd", fg="#ffffff",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", activebackground="#04a87d",
    state="disabled"
)
btn_iniciar.pack(side="left", padx=(0, 8))

btn_stop = tk.Button(
    frame_btns, text="⏹  Interrumpir",
    command=None,
    bg="#a5a5ee", fg="#888",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", state="disabled",
    activebackground="#6a2040"
)
btn_stop.pack(side="left")

btn_procesar_texto = tk.Button(
    frame_btns, text="  Procesar Texto",
    command=None,
    bg="#06d6a0", fg="#ffffff",
    font=("Consolas", 11, "bold"),
    relief="flat", padx=16, pady=8,
    cursor="hand2", activebackground="#04a87d"
)
# Inicialmente oculto
btn_procesar_texto.pack_forget()

# Mini frame para el modelo
frame_mini_model = tk.Frame(frame_btns, bg="#0d0d1a")
frame_mini_model.pack(fill="x", pady=(0, 4), side="right")

lbl_text_model_mini = tk.Label(
    frame_mini_model, text="Selecciona un modelo",
    bg="#0d0d1a",fg="#a5a5ee",
    font=("Consolas", 14, "bold")
)
lbl_text_model_mini.pack(pady=(0, 8), padx=8, side="top", anchor="center")

combo_after = ttk.Combobox(frame_mini_model, textvariable=var_modelo, state="readonly")
combo_after['values'] = []
combo_after.pack()


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