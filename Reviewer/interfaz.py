import sys
from pathlib import Path
import markdown
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget,
    QMainWindow, QProgressBar, QPushButton, QSizePolicy, QStackedWidget,
    QTextEdit, QVBoxLayout, QWidget, QFileDialog
)
from PySide6.QtWebEngineWidgets import QWebEngineView

# Import centralized paths from state
from state import REVIEW_DIR, TEXTOS_DIR

_buffer = []
after_display = False

_IMGS = Path(__file__).parent / "imgs"

#CONSTANTES DE ESTILOS
FONT_SIZE = {"title": 32, "subtitle": 14, "label": 11, "small": 9, "tiny": 8}
PADDING = {"normal": "10px 16px", "compact": "8px 14px", "tight": "6px 10px"}

# MARKDOWN - HTML
def _md_a_html(texto: str) -> str:
    cuerpo = markdown.markdown(texto, extensions=["extra", "nl2br"])
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    background: #0F2C59;
    color: #F4F6F9;
    font-family: 'Segoe UI', Calibri, sans-serif;
    font-size: 13px;
    padding: 18px;
    line-height: 1.75;
    margin: 0;
  }}
  h1 {{ color: #F4F6F9; font-size: 20px; border-bottom: 1px solid #17365F; padding-bottom: 6px; }}
  h2 {{ color: #E2E8F0; font-size: 16px; margin-top: 18px; }}
  h3 {{ color: #CBD5E1; font-size: 14px; margin-top: 14px; }}
  strong {{ color: #FFFFFF; }}
  em {{ color: #CBD5E1; }}
  code {{
    background: rgba(255,255,255,0.08);
    color: #F4F6F9;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 12px;
  }}
  pre {{
    background: rgba(255,255,255,0.08);
    color: #F4F6F9;
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
  }}
  blockquote {{
    border-left: 3px solid #7A1C20;
    margin: 10px 0;
    padding-left: 14px;
    color: #CBD5E1;
  }}
  ul, ol {{ padding-left: 22px; }}
  li {{ margin: 4px 0; }}
  li::marker {{ color: #7A1C20; }}
  hr {{ border: none; border-top: 1px solid rgba(255,255,255,0.12); margin: 16px 0; }}
  p {{ margin: 8px 0; }}
</style>
</head>
<body>{cuerpo}</body>
</html>"""

COLORES = {
    "fondo_principal": "#F4F6F9",
    "fondo_menu": "#E2E8F0",
    "fondo_carta": "#0F2C59",
    "fondo_notas": "#F4F6F9",
    "boton_acento": "#7A1C20",
    "texto_principal": "#1E293B",
    "texto_secundario": "#475569",
    "blanco_crisp": "#FFFFFF",
    "gris_claro": "#CBD5E1",
}

def _estilo_etiqueta_estado(color: str) -> str:
    return (
        f"color: {color}; background-color: {color}22;"
        f" border-left: 3px solid {color}; padding: 5px 10px;"
        f" border-radius: 4px; font-family: 'Segoe UI'; font-size: 9px;"
    )

def _estilo_barra_progreso(color: str) -> str:
    return (
        f"QProgressBar {{ background: #23406F; border: none; border-radius: 5px;"
        f" height: 10px; }}"
        f"QProgressBar::chunk {{ background: {color}; border-radius: 5px; }}"
    )

class _UiDispatcher(QObject):
    """Ejecuta callbacks en el hilo principal (seguro desde worker threads)."""
    invoke = Signal(object)

    def __init__(self):
        super().__init__()
        self.invoke.connect(lambda fn: fn(), Qt.ConnectionType.QueuedConnection)

_ui_dispatcher = None

def _init_ui_dispatcher():
    global _ui_dispatcher
    _ui_dispatcher = _UiDispatcher()

def _ui(fn):
    _ui_dispatcher.invoke.emit(fn)

def set_estado(texto: str, color: str = "#4a4a8a"):
    """Actualiza la etiqueta de estado con texto y color."""
    _ui(lambda: lbl_estado_w.setText(texto))
    _ui(lambda: lbl_estado_w.setStyleSheet(_estilo_etiqueta_estado(color)))

def set_modelo_display(texto: str, color: str = "#4a4a8a"):
    """Actualiza el label de modelo en pantalla inicial y en pantalla de trabajo."""
    def _do():
        lbl_text_first_model.setText(texto)
        lbl_text_first_model.setStyleSheet(_estilo_etiqueta_estado(color))
        lbl_text_model_mini_w.setText(texto)
        lbl_text_model_mini_w.setStyleSheet(_estilo_etiqueta_estado(color))
    _ui(_do)

def set_progreso(valor: int):
    """Establece el valor de la barra de progreso (0-100)."""
    _ui(lambda: progress_bar_w.setValue(valor))

# --- Etapas del pipeline (etiqueta, color, rango 0-100) ---
ETAPAS = {
    "reposo": {
        "etiqueta": "Listo",
        "mensaje": "Esperando acción…",
        "color": "#94A3B8",
        "progreso": (0, 0),
    },
    "preparado": {
        "etiqueta": "Listo",
        "mensaje": "Documento y modelo listos.",
        "color": "#06D6A0",
        "progreso": (0, 0),
    },
    "iniciando": {
        "etiqueta": "Inicio",
        "mensaje": "Iniciando revisión…",
        "color": "#06D6A0",
        "progreso": (0, 2),
    },
    "extraccion_texto": {
        "etiqueta": "Texto",
        "mensaje": "Extrayendo texto del documento…",
        "color": "#06D6A0",
        "progreso": (2, 12),
    },
    "segmentacion": {
        "etiqueta": "Secciones",
        "mensaje": "Segmentando el documento por secciones…",
        "color": "#06D6A0",
        "progreso": (12, 20),
    },
    "embeddings": {
        "etiqueta": "Embeddings",
        "mensaje": "Generando embeddings semánticos…",
        "color": "#06D6A0",
        "progreso": (20, 30),
    },
    "chunking": {
        "etiqueta": "Segmentación",
        "mensaje": "Dividiendo el documento en fragmentos…",
        "color": "#06D6A0",
        "progreso": (30, 38),
    },
    "metodologia": {
        "etiqueta": "Metodología",
        "mensaje": "Analizando secciones de metodología…",
        "color": "#06D6A0",
        "progreso": (38, 52),
    },
    "chroma": {
        "etiqueta": "ChromaDB",
        "mensaje": "Buscando revisiones similares…",
        "color": "#06D6A0",
        "progreso": (52, 58),
    },
    "prompt": {
        "etiqueta": "Prompt",
        "mensaje": "Construyendo el prompt de revisión…",
        "color": "#06D6A0",
        "progreso": (58, 62),
    },
    "revision": {
        "etiqueta": "Revisión",
        "mensaje": "Generando revisión con el modelo…",
        "color": "#06D6A0",
        "progreso": (62, 92),
    },
    "guardando": {
        "etiqueta": "Guardado",
        "mensaje": "Guardando reporte y archivos…",
        "color": "#06D6A0",
        "progreso": (92, 98),
    },
    "completado": {
        "etiqueta": "Completado",
        "mensaje": "Revisión completada.",
        "color": "#06D6A0",
        "progreso": (100, 100),
    },
    "advertencia": {
        "etiqueta": "Aviso",
        "mensaje": "",
        "color": "#E9C46A",
        "progreso": (92, 98),
    },
    "error": {
        "etiqueta": "Error",
        "mensaje": "",
        "color": "#E94560",
        "progreso": (0, 0),
    },
}

def _aplicar_etapa(texto: str, color: str, valor: int):
    lbl_estado_w.setText(texto)
    lbl_estado_w.setStyleSheet(_estilo_etiqueta_estado(color))
    progress_bar_w.setValue(valor)
    progress_bar_w.setStyleSheet(_estilo_barra_progreso(color))

def reportar_etapa(clave: str, sub: float = 0.0, detalle: str | None = None):
    """
    Actualiza etiqueta coloreada y barra de progreso según la etapa del pipeline.
    
    Args:
        clave: Identificador de la etapa (ej: "extraccion_texto", "revision", "error")
        sub: Progreso dentro de la etapa, rango 0.0-1.0 (interpolado en el rango de la etapa)
        detalle: Mensaje personalizado (si None, usa el mensaje predeterminado)
    """
    info = ETAPAS.get(clave, ETAPAS["reposo"])
    inicio, fin = info["progreso"]
    sub = max(0.0, min(1.0, sub))
    valor = inicio if inicio == fin else int(inicio + (fin - inicio) * sub)
    mensaje = detalle or info["mensaje"]
    texto = f"{info['etiqueta']} · {mensaje}"
    color = info["color"]
    _ui(lambda t=texto, c=color, v=valor: _aplicar_etapa(t, c, v))

def reportar_error(mensaje: str):
    """Reporta un error actualizando la etiqueta y manteniendo la barra de progreso."""
    info = ETAPAS["error"]
    texto = f"{info['etiqueta']} · {mensaje}"
    _ui(lambda t=texto, c=info["color"]: _aplicar_etapa(t, c, progress_bar_w.value()))

def escribir_salida(texto: str):
    """Renderiza texto Markdown como HTML en el área de salida."""
    _ui(lambda: _salida_w.setHtml(_md_a_html(texto), QUrl("about:blank")))

def append_salida(token: str):
    """
    Agrega un token al buffer de streaming y renderiza cada 40 tokens.
    Usado para mostrar revisiones mientras se generan.
    """
    _buffer.append(token)
    if len(_buffer) % 40 == 0:
        escribir_salida("".join(_buffer))

def _finalizar_streaming():
    """Renderiza el buffer completo como HTML en el area de salida."""
    texto_completo = "".join(_buffer)
    _buffer.clear()
    escribir_salida(texto_completo)

def cargar_historial():
    """Carga la lista de revisiones guardadas (archivos .md)."""
    _lista_hist_w.clear()
    archivos = sorted(REVIEW_DIR.glob("*.md"), reverse=True)
    if not archivos:
        _lista_hist_w.addItem("  (sin revisiones)")
        return
    for f in archivos:
        _lista_hist_w.addItem(f"{f.stem}")

def cargar_textos():
    """Carga la lista de textos extraídos (archivos .txt)."""
    _lista_txt_w.clear()
    textos = sorted(TEXTOS_DIR.glob("*.txt"), reverse=True)
    if not textos:
        _lista_txt_w.addItem("  (sin textos)")
        return
    for f in textos:
        _lista_txt_w.addItem(f"{f.stem}")

def iniciar_display_derecho():
    """Cambia a la vista de trabajo (salida de revisión)."""
    global after_display
    stacked_right.setCurrentIndex(1)
    after_display = True

def volver_display_inicial():
    """Cambia a la vista inicial (pantalla de bienvenida)."""
    global after_display
    stacked_right.setCurrentIndex(0)
    after_display = False

def ask_open_file(title: str, file_filter: str) -> str:
    """
    Abre diálogo para seleccionar archivo.
    
    Returns:
        Ruta del archivo seleccionado (vacío si se cancela)
    """
    ruta, _ = QFileDialog.getOpenFileName(_main, title, "", file_filter)
    return ruta or ""

# Funciones de control de la UI para uso en reviewer.py
def set_lbl_archivo(texto: str, color: str):
    _ui(lambda: lbl_archivo_w.setText(texto))
    _ui(lambda: lbl_archivo_w.setStyleSheet(f"color: {color}; background: transparent; font-family: 'Segoe UI'; font-size: {FONT_SIZE['tiny']}px;"))

def set_btn_iniciar_state(enabled: bool):
    _ui(lambda: btn_iniciar_w.setEnabled(enabled))

def set_btn_stop_state(enabled: bool):
    _ui(lambda: btn_stop_w.setEnabled(enabled))

def set_modo_proceso(activo: bool):
    """Alterna el estado de los botones Iniciar/Detener según si hay un proceso activo."""
    _ui(lambda: btn_iniciar_w.setEnabled(not activo))
    _ui(lambda: btn_stop_w.setEnabled(activo))

def set_btn_procesar_texto_visible(visible: bool):
    _ui(lambda: (btn_procesar_texto_w.show() if visible else btn_procesar_texto_w.hide()))

def set_modelos(modelos: list[str]):
    def _set():
        for combo in [_combo_first_w, _combo_after_w]:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(modelos)
            combo.blockSignals(False)
    _ui(_set)

def get_modelo_seleccionado() -> str:
    return _combo_after_w.currentText()

def set_modelo_seleccionado(modelo: str):
    def _set():
        for combo in [_combo_first_w, _combo_after_w]:
            combo.blockSignals(True)
            idx = combo.findText(modelo)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)
    _ui(_set)

def get_historial_seleccion() -> str | None:
    item = _lista_hist_w.currentItem()
    return item.text().strip() if item else None

def get_texto_seleccionado() -> str | None:
    item = _lista_txt_w.currentItem()
    return item.text().strip() if item else None

def ejecutar_app():
    _main.show()
    app.exec()

def after(ms: int, callback):
    QTimer.singleShot(ms, callback)

# Estilos de widgets
def _btn_style(bg, fg, hover=None, padding=PADDING["normal"]):
    hover = hover or bg
    return (
        f"QPushButton {{ background-color: {bg}; color: {fg}; border: none;"
        f" padding: {padding}; font-family: 'Segoe UI'; font-size: {FONT_SIZE['label']}px;"
        f" font-weight: bold; border-radius: 4px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
        f"QPushButton:disabled {{ background-color: #94A3B8; color: #E2E8F0; }}"
    )

def _list_style():
    return (
        f"QListWidget {{ background: {COLORES['blanco_crisp']}; color: {COLORES['texto_principal']};"
        f" border: none; font-family: 'Segoe UI'; font-size: 11px; }}"
        f"QListWidget::item:selected {{ background: {COLORES['boton_acento']};"
        f" color: {COLORES['blanco_crisp']}; }}"
    )

def _separator(parent, color=None):
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background: {color or COLORES['gris_claro']}; max-height: 1px;")
    return line

# Construcción de la interfaz PySide6
app = QApplication.instance() or QApplication(sys.argv)
_init_ui_dispatcher()

_main = QMainWindow()
_main.setWindowTitle("Revisor de PDF")
_main.resize(1240, 760)
_main.setStyleSheet(f"background-color: {COLORES['fondo_principal']};")

_central = QWidget()
_main.setCentralWidget(_central)
_layout_main = QHBoxLayout(_central)
_layout_main.setContentsMargins(14, 14, 14, 14)
_layout_main.setSpacing(8)

# Panel izquierdo
frame_left = QWidget()
frame_left.setFixedWidth(300)
frame_left.setStyleSheet(f"background-color: {COLORES['fondo_menu']};")
_layout_left = QVBoxLayout(frame_left)
_layout_left.setContentsMargins(18, 18, 18, 18)
_layout_left.setSpacing(8)

_logo_small = QPixmap(str(_IMGS / "logo.png")).scaled(
    180, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
)
btn_logo_sidebar_w = QPushButton()
btn_logo_sidebar_w.setFlat(True)
btn_logo_sidebar_w.setIcon(QIcon(_logo_small))
btn_logo_sidebar_w.setIconSize(_logo_small.size())
btn_logo_sidebar_w.setStyleSheet(f"background: {COLORES['fondo_menu']}; border: none;")
btn_logo_sidebar_w.setCursor(Qt.CursorShape.PointingHandCursor)
btn_logo_sidebar_w.clicked.connect(volver_display_inicial)
_layout_left.addWidget(btn_logo_sidebar_w, alignment=Qt.AlignmentFlag.AlignHCenter)
_layout_left.addWidget(_separator(frame_left))

frame_left_actions = QWidget()
_layout_actions = QVBoxLayout(frame_left_actions)
_layout_actions.setContentsMargins(0, 0, 0, 0)
_layout_actions.setSpacing(10)

_btn_adj_style = _btn_style(COLORES["blanco_crisp"], COLORES["texto_principal"], "#F8FAFC")
btn_adjuntar_prev_w = QPushButton("Nuevo Archivo")
btn_adjuntar_prev_w.setStyleSheet(_btn_adj_style)
btn_adjuntar_prev_w.setCursor(Qt.CursorShape.PointingHandCursor)
_layout_actions.addWidget(btn_adjuntar_prev_w)

btn_adjuntar_w = QPushButton("Buscar PDF")
btn_adjuntar_w.setStyleSheet(_btn_adj_style)
btn_adjuntar_w.setCursor(Qt.CursorShape.PointingHandCursor)
_layout_actions.addWidget(btn_adjuntar_w)
_layout_left.addWidget(frame_left_actions)

_lbl_recientes = QLabel("ARCHIVOS RECIENTES")
_lbl_recientes.setStyleSheet(
    f"color: {COLORES['texto_principal']}; font-family: 'Segoe UI';"
    f" font-size: {FONT_SIZE['small']}px; font-weight: bold; background: {COLORES['fondo_menu']};"
)
_layout_left.addWidget(_lbl_recientes)
_layout_left.addWidget(_separator(frame_left))

_lista_hist_w = QListWidget()
_lista_hist_w.setStyleSheet(_list_style())
_lista_hist_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
_layout_left.addWidget(_lista_hist_w, stretch=1)

_lbl_textos = QLabel("Textos Guardados")
_lbl_textos.setStyleSheet(
    f"color: {COLORES['texto_secundario']}; font-family: 'Segoe UI';"
    f" font-size: {FONT_SIZE['tiny']}px; font-style: italic; background: {COLORES['fondo_menu']};"
)
_layout_left.addWidget(_lbl_textos)

_lista_txt_w = QListWidget()
_lista_txt_w.setMaximumHeight(120)
_lista_txt_w.setStyleSheet(_list_style())
_layout_left.addWidget(_lista_txt_w)

_layout_main.addWidget(frame_left)

# Panel derecho (stacked: bienvenida / trabajo)
stacked_right = QStackedWidget()
stacked_right.setStyleSheet(f"background-color: {COLORES['fondo_principal']};")

# --- Pantalla inicial ---
frame_right_first = QWidget()
_layout_welcome = QVBoxLayout(frame_right_first)
_layout_welcome.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
_layout_welcome.setContentsMargins(8, 80, 8, 8)

_logo_large = QPixmap(str(_IMGS / "logo.png")).scaled(
    320, 140, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
)
btn_logo = QLabel()
btn_logo.setPixmap(_logo_large)
btn_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
_layout_welcome.addWidget(btn_logo)

lbl_title = QLabel("Revisor de PDF")
lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
lbl_title.setStyleSheet(
    f"color: {COLORES['texto_principal']}; font-family: 'Segoe UI';"
    f" font-size: {FONT_SIZE['title']}px; font-weight: bold; background: transparent;"
)
_layout_welcome.addWidget(lbl_title)

lbl_text_first = QLabel("Cargue un archivo PDF para iniciar el análisis académico.")
lbl_text_first.setAlignment(Qt.AlignmentFlag.AlignCenter)
lbl_text_first.setWordWrap(True)
lbl_text_first.setMaximumWidth(560)
lbl_text_first.setStyleSheet(
    f"color: {COLORES['texto_secundario']}; font-family: 'Segoe UI';"
    f" font-size: 12px; background: transparent;"
)
_layout_welcome.addWidget(lbl_text_first)

lbl_text_first_model = QLabel("Seleccione un modelo para comenzar.")
lbl_text_first_model.setAlignment(Qt.AlignmentFlag.AlignCenter)
lbl_text_first_model.setStyleSheet(
    f"color: {COLORES['texto_secundario']}; font-family: 'Segoe UI';"
    f" font-size: {FONT_SIZE['label']}px; background: transparent;"
)
_layout_welcome.addWidget(lbl_text_first_model)

_combo_first_w = QComboBox()
_combo_first_w.setMinimumWidth(280)
_combo_style = (
    f"QComboBox {{ background: {COLORES['blanco_crisp']}; color: {COLORES['texto_principal']};"
    f" padding: 8px; border: 1px solid {COLORES['gris_claro']}; border-radius: 4px;"
    f" font-family: 'Segoe UI'; }}"
    f"QComboBox::drop-down {{ border: none; }}"
    f"QComboBox QAbstractItemView {{ background: {COLORES['blanco_crisp']};"
    f" color: {COLORES['texto_principal']};"
    f" selection-background-color: {COLORES['boton_acento']};"
    f" selection-color: {COLORES['blanco_crisp']}; }}"
    f"QComboBox QAbstractItemView::item {{ color: {COLORES['texto_principal']};"
    f" padding: 6px 10px; min-height: 24px; }}"
    f"QComboBox QAbstractItemView::item:selected {{"
    f" background: {COLORES['boton_acento']}; color: {COLORES['blanco_crisp']}; }}"
)
_combo_first_w.setStyleSheet(_combo_style)
_layout_welcome.addWidget(_combo_first_w, alignment=Qt.AlignmentFlag.AlignHCenter)
_layout_welcome.addStretch()

stacked_right.addWidget(frame_right_first)

# --- Pantalla de trabajo ---
frame_right = QWidget()
_layout_right = QVBoxLayout(frame_right)
_layout_right.setContentsMargins(0, 0, 0, 0)
_layout_right.setSpacing(16)

frame_top_card = QWidget()
frame_top_card.setStyleSheet(
    f"background-color: {COLORES['fondo_carta']}; border-radius: 8px;"
)
_layout_card = QVBoxLayout(frame_top_card)
_layout_card.setContentsMargins(24, 24, 24, 24)
_layout_card.setSpacing(12)

frame_btns = QWidget()
_layout_btns = QHBoxLayout(frame_btns)
_layout_btns.setContentsMargins(0, 0, 0, 0)
_layout_btns.setSpacing(12)

btn_iniciar_w = QPushButton("▶ Iniciar Revisión")
btn_iniciar_w.setStyleSheet(_btn_style(COLORES["boton_acento"], COLORES["blanco_crisp"], "#94161D"))
btn_iniciar_w.setEnabled(False)
btn_iniciar_w.setCursor(Qt.CursorShape.PointingHandCursor)
_layout_btns.addWidget(btn_iniciar_w)

btn_stop_w = QPushButton("⏹ Detener")
btn_stop_w.setStyleSheet(_btn_style("#D9E2EC", COLORES["texto_principal"], "#BAC8D6"))
btn_stop_w.setEnabled(False)
btn_stop_w.setCursor(Qt.CursorShape.PointingHandCursor)
_layout_btns.addWidget(btn_stop_w)

btn_procesar_texto_w = QPushButton("Procesar Texto")
btn_procesar_texto_w.setStyleSheet(_btn_style("#475569", COLORES["blanco_crisp"], "#344A5E"))
btn_procesar_texto_w.setCursor(Qt.CursorShape.PointingHandCursor)
btn_procesar_texto_w.hide()
_layout_btns.addWidget(btn_procesar_texto_w)

_layout_btns.addStretch()

frame_mini_model = QWidget()
_layout_mini = QVBoxLayout(frame_mini_model)
_layout_mini.setAlignment(Qt.AlignmentFlag.AlignRight)
lbl_text_model_mini_w = QLabel("Seleccionar modelo")
lbl_text_model_mini_w.setAlignment(Qt.AlignmentFlag.AlignRight)
lbl_text_model_mini_w.setStyleSheet(
    f"color: {COLORES['gris_claro']}; font-family: 'Segoe UI';"
    f" font-size: {FONT_SIZE['label']}px; background: transparent;"
)
_layout_mini.addWidget(lbl_text_model_mini_w)

_combo_after_w = QComboBox()
_combo_after_w.setStyleSheet(_combo_style)
_combo_after_w.setMinimumWidth(200)
_layout_mini.addWidget(_combo_after_w)
_layout_btns.addWidget(frame_mini_model)

btn_volver_header_w = QPushButton("← Volver")
btn_volver_header_w.setStyleSheet(_btn_style("#475569", COLORES["blanco_crisp"], "#344A5E", "8px 14px"))
btn_volver_header_w.setCursor(Qt.CursorShape.PointingHandCursor)
btn_volver_header_w.clicked.connect(volver_display_inicial)
_layout_btns.addWidget(btn_volver_header_w)

_layout_card.addWidget(frame_btns)

lbl_archivo_w = QLabel("Ningún archivo seleccionado")
lbl_archivo_w.setStyleSheet(
    f"color: {COLORES['gris_claro']}; font-family: 'Segoe UI';"
    f" font-size: {FONT_SIZE['small']}px; background: transparent;"
)
_layout_card.addWidget(lbl_archivo_w)

frame_prog = QWidget()
_layout_prog = QVBoxLayout(frame_prog)
_layout_prog.setContentsMargins(0, 0, 0, 0)

progress_bar_w = QProgressBar()
progress_bar_w.setRange(0, 100)
progress_bar_w.setValue(0)
progress_bar_w.setTextVisible(False)
progress_bar_w.setStyleSheet(
    f"QProgressBar {{ background: #23406F; border: none; border-radius: 5px; height: 10px; }}"
    f"QProgressBar::chunk {{ background: {COLORES['boton_acento']}; border-radius: 5px; }}"
)
_layout_prog.addWidget(progress_bar_w)

lbl_estado_w = QLabel("Esperando acción...")
lbl_estado_w.setStyleSheet(
    f"color: {COLORES['gris_claro']}; font-family: 'Segoe UI';"
    f" font-size: {FONT_SIZE['small']}px; background: transparent;"
)
_layout_prog.addWidget(lbl_estado_w)
_layout_card.addWidget(frame_prog)

_salida_w = QWebEngineView()
_salida_w.setMinimumHeight(280)
_layout_card.addWidget(_salida_w, stretch=1)

_layout_right.addWidget(frame_top_card, stretch=3)

frame_notes_card = QWidget()
frame_notes_card.setStyleSheet(
    f"background-color: {COLORES['fondo_notas']}; border-radius: 8px;"
)
_layout_notes = QVBoxLayout(frame_notes_card)
_layout_notes.setContentsMargins(22, 22, 22, 22)

lbl_notes_title_w = QLabel(" Notas")
lbl_notes_title_w.setStyleSheet(
    f"color: {COLORES['texto_principal']}; font-family: 'Segoe UI';"
    f" font-size: {FONT_SIZE['subtitle']}px; font-weight: bold;"
)
_layout_notes.addWidget(lbl_notes_title_w)

lbl_notes_sub_w = QLabel(
    "Capture observaciones y anotaciones de la revisión en esta sección."
)
lbl_notes_sub_w.setWordWrap(True)
lbl_notes_sub_w.setStyleSheet(
    f"color: {COLORES['texto_secundario']}; font-family: 'Segoe UI'; font-size: 10px;"
)
_layout_notes.addWidget(lbl_notes_sub_w)

txt_notas_w = QTextEdit()
txt_notas_w.setPlainText("Notas de revisión académica...")
txt_notas_w.setStyleSheet(
    f"background: {COLORES['blanco_crisp']}; color: {COLORES['texto_principal']};"
    f" border: none; font-family: 'Segoe UI'; font-size: 11px; padding: 14px;"
)
_layout_notes.addWidget(txt_notas_w)

_layout_right.addWidget(frame_notes_card, stretch=1)
stacked_right.addWidget(frame_right)

_layout_main.addWidget(stacked_right, stretch=1)

# Sincronización entre los dos comboboxes de selección de modelo
def _sync_combos(target: QComboBox, index: int):
    if index < 0 or index >= target.count():
        return
    target.blockSignals(True)
    target.setCurrentIndex(index)
    target.blockSignals(False)

_combo_first_w.activated.connect(lambda idx: _sync_combos(_combo_after_w, idx))
_combo_after_w.activated.connect(lambda idx: _sync_combos(_combo_first_w, idx))

# Conectar controladores y callbacks
def wire_commands(
    on_adjuntar=None,
    on_iniciar=None,
    on_stop=None,
    on_procesar_texto=None,
):
    """Conecta acciones a botones (Qt signals, hilo principal)."""
    if on_adjuntar:
        btn_adjuntar_prev_w.clicked.connect(on_adjuntar)
        btn_adjuntar_w.clicked.connect(on_adjuntar)
    if on_iniciar:
        btn_iniciar_w.clicked.connect(on_iniciar)
    if on_stop:
        btn_stop_w.clicked.connect(on_stop)
    if on_procesar_texto:
        btn_procesar_texto_w.clicked.connect(on_procesar_texto)

def conectar_seleccion_modelo(callback):
    _combo_first_w.activated.connect(lambda _i: callback(None))
    _combo_first_w.currentIndexChanged.connect(lambda _i: callback(None))
    _combo_after_w.activated.connect(lambda _i: callback(None))
    _combo_after_w.currentIndexChanged.connect(lambda _i: callback(None))

def conectar_seleccion_historial(callback):
    _lista_hist_w.itemSelectionChanged.connect(lambda: callback(None))

def conectar_seleccion_textos(callback):
    _lista_txt_w.itemSelectionChanged.connect(lambda: callback(None))
