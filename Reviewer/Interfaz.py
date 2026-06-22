import sys
from pathlib import Path

import markdown
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

_buffer = []
after_display = False
REVIEW_DIR = None
TEXTOS_DIR = None

_IMGS = Path(__file__).parent / "imgs"


#  MARKDOWN - HTML
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


# --- Adaptadores (API compatible con tkinter para reviewer.py) ---

class _LabelAdapter:
    def __init__(self, label: QLabel):
        self._w = label

    def config(self, **kwargs):
        if "text" in kwargs:
            self._w.setText(kwargs["text"])
        if "fg" in kwargs:
            self._w.setStyleSheet(f"color: {kwargs['fg']};")


class _ButtonAdapter:
    def __init__(self, button: QPushButton):
        self._w = button

    def config(self, state=None, command=None, **kwargs):
        if state == "normal":
            self._w.setEnabled(True)
        elif state == "disabled":
            self._w.setEnabled(False)
        if command is not None:
            try:
                self._w.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._w.clicked.connect(command)

    def pack(self, **kwargs):
        self._w.show()

    def pack_forget(self):
        self._w.hide()


class _ListAdapter:
    def __init__(self, widget: QListWidget):
        self._w = widget

    def delete(self, start, end):
        self._w.clear()

    def insert(self, end, item):
        self._w.addItem(item)

    def curselection(self):
        row = self._w.currentRow()
        return () if row < 0 else (row,)

    def get(self, index):
        item = self._w.item(index)
        return item.text() if item else ""

    def bind(self, event, callback):
        if event == "<<ListboxSelect>>":
            self._w.itemSelectionChanged.connect(lambda: callback(None))


class _ComboAdapter:
    def __init__(self, combo: QComboBox, var: "_StringVarAdapter"):
        self._w = combo
        self._var = var

    def __setitem__(self, key, value):
        if key == "values":
            self._w.blockSignals(True)
            self._w.clear()
            self._w.addItems(value)
            self._w.blockSignals(False)

    def bind(self, event, callback):
        if event == "<<ComboboxSelected>>":
            self._w.activated.connect(lambda _i: callback(None))


class _StringVarAdapter:
    def __init__(self, combos: list[QComboBox]):
        self._combos = combos

    def get(self):
        if not self._combos:
            return ""
        return self._combos[0].currentText()

    def set(self, value: str):
        for combo in self._combos:
            combo.blockSignals(True)
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)


class _HtmlAdapter:
    def __init__(self, view: QWebEngineView):
        self._w = view

    def load_html(self, html: str):
        self._w.setHtml(html, QUrl("about:blank"))


class _ProgressAdapter:
    def __init__(self, bar: QProgressBar):
        self._w = bar

    def config(self, value=None, **kwargs):
        if value is not None:
            self._w.setValue(value)


# UI HELPERS

def _ui(fn):
    QTimer.singleShot(0, fn)


def set_estado(texto: str, color: str = "#4a4a8a"):
    _ui(lambda: lbl_estado.config(text=texto, fg=color))


def set_modelo_first(texto: str, color: str = "#4a4a8a"):
    _ui(lambda: lbl_text_first_model.config(text=texto, fg=color))


def set_modelo_after(texto: str, color: str = "#4a4a8a"):
    _ui(lambda: lbl_text_model_mini.config(text=texto, fg=color))


def set_progreso(valor: int):
    _ui(lambda: progress_bar.config(value=valor))


def escribir_salida(texto: str):
    def _w():
        salida_html.load_html(_md_a_html(texto))

    _ui(_w)


def escribir_plano(texto: str):
    def _w():
        salida_html.load_html(_md_a_html(texto))

    _ui(_w)


def append_salida(token: str):
    _buffer.append(token)
    if len(_buffer) % 40 == 0:
        texto_hasta_ahora = "".join(_buffer)
        _ui(lambda t=texto_hasta_ahora: salida_html.load_html(_md_a_html(t)))


def _finalizar_streaming():
    texto_completo = "".join(_buffer)
    _buffer.clear()
    _ui(lambda: salida_html.load_html(_md_a_html(texto_completo)))


def _restaurar_botones():
    def _do():
        btn_iniciar.config(state="normal")
        btn_stop.config(state="disabled")

    _ui(_do)


def display_inicial():
    volver_display_inicial()


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


def iniciar_display_derecho():
    global after_display
    stacked_right.setCurrentIndex(1)
    after_display = True


def volver_display_inicial():
    global after_display
    stacked_right.setCurrentIndex(0)
    after_display = False


def ask_open_file(title: str, file_filter: str) -> str:
    """Diálogo de archivo compatible con filedialog.askopenfilename."""
    from PySide6.QtWidgets import QFileDialog

    ruta, _ = QFileDialog.getOpenFileName(_main, title, "", file_filter)
    return ruta or ""


def _btn_style(bg, fg, hover=None, padding="10px 16px"):
    hover = hover or bg
    return (
        f"QPushButton {{ background-color: {bg}; color: {fg}; border: none;"
        f" padding: {padding}; font-family: 'Segoe UI'; font-size: 11px;"
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


class _RootAdapter:
    """Expone mainloop() y after() como en tkinter."""

    def __init__(self, window: QMainWindow, application: QApplication):
        self._window = window
        self._app = application

    def mainloop(self):
        self._window.show()
        self._app.exec()

    def after(self, _ms, fn):
        QTimer.singleShot(0, fn)


def _separator(parent, color=None):
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background: {color or COLORES['gris_claro']}; max-height: 1px;")
    return line


# --- Construcción de la interfaz ---

app = QApplication.instance() or QApplication(sys.argv)

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
btn_adjuntar_prev = QPushButton("Nuevo Archivo")
btn_adjuntar_prev.setStyleSheet(_btn_adj_style)
btn_adjuntar_prev.setCursor(Qt.CursorShape.PointingHandCursor)
_layout_actions.addWidget(btn_adjuntar_prev)

btn_adjuntar = QPushButton("Buscar PDF")
btn_adjuntar.setStyleSheet(_btn_adj_style)
btn_adjuntar.setCursor(Qt.CursorShape.PointingHandCursor)
_layout_actions.addWidget(btn_adjuntar)
_layout_left.addWidget(frame_left_actions)

_lbl_recientes = QLabel("ARCHIVOS RECIENTES")
_lbl_recientes.setStyleSheet(
    f"color: {COLORES['texto_principal']}; font-family: 'Segoe UI';"
    f" font-size: 9px; font-weight: bold; background: {COLORES['fondo_menu']};"
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
    f" font-size: 8px; font-style: italic; background: {COLORES['fondo_menu']};"
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
    f" font-size: 32px; font-weight: bold; background: transparent;"
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
    f" font-size: 11px; background: transparent;"
)
_layout_welcome.addWidget(lbl_text_first_model)

_combo_first_w = QComboBox()
_combo_first_w.setMinimumWidth(280)
_combo_style = (
    f"QComboBox {{ background: {COLORES['blanco_crisp']}; color: {COLORES['texto_principal']};"
    f" padding: 8px; border: 1px solid {COLORES['gris_claro']}; border-radius: 4px;"
    f" font-family: 'Segoe UI'; }}"
    f"QComboBox QAbstractItemView {{ background: {COLORES['blanco_crisp']};"
    f" selection-background-color: {COLORES['boton_acento']};"
    f" selection-color: {COLORES['blanco_crisp']}; }}"
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
    f" font-size: 11px; background: transparent;"
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
    f" font-size: 9px; background: transparent;"
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
    f" font-size: 9px; background: transparent;"
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
    f" font-size: 14px; font-weight: bold;"
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

def _sync_combo_from_first(index: int):
    if index < 0 or index >= _combo_after_w.count():
        return
    _combo_after_w.blockSignals(True)
    _combo_after_w.setCurrentIndex(index)
    _combo_after_w.blockSignals(False)


def _sync_combo_from_after(index: int):
    if index < 0 or index >= _combo_first_w.count():
        return
    _combo_first_w.blockSignals(True)
    _combo_first_w.setCurrentIndex(index)
    _combo_first_w.blockSignals(False)


_combo_first_w.activated.connect(_sync_combo_from_first)
_combo_after_w.activated.connect(_sync_combo_from_after)

# Adaptadores exportados (misma API que tkinter)
root = _RootAdapter(_main, app)
var_modelo = _StringVarAdapter([_combo_first_w, _combo_after_w])

lbl_archivo = _LabelAdapter(lbl_archivo_w)
lbl_estado = _LabelAdapter(lbl_estado_w)
lbl_text_first_model = _LabelAdapter(lbl_text_first_model)
lbl_text_model_mini = _LabelAdapter(lbl_text_model_mini_w)

btn_iniciar = _ButtonAdapter(btn_iniciar_w)
btn_stop = _ButtonAdapter(btn_stop_w)
btn_procesar_texto = _ButtonAdapter(btn_procesar_texto_w)
btn_adjuntar_prev = _ButtonAdapter(btn_adjuntar_prev)
btn_adjuntar = _ButtonAdapter(btn_adjuntar)
btn_volver_header = _ButtonAdapter(btn_volver_header_w)
btn_logo_sidebar = _ButtonAdapter(btn_logo_sidebar_w)
# btn_logo es QLabel en pantalla de bienvenida

lista_historial = _ListAdapter(_lista_hist_w)
lista_textos = _ListAdapter(_lista_txt_w)
combo_first = _ComboAdapter(_combo_first_w, var_modelo)
combo_after = _ComboAdapter(_combo_after_w, var_modelo)
salida_html = _HtmlAdapter(_salida_w)
progress_bar = _ProgressAdapter(progress_bar_w)
txt_notas = txt_notas_w
