# Disponible para versión 3.11
import shutil
import threading
from pathlib import Path

import ollama

import interfaz as UIF
from state import RevisionState, PDF_DIR, OLLAMA_HOST
from document import DocumentManager
from pipeline import ReviewPipeline


# ESTADO Y DEPENDENCIAS

state = RevisionState()
doc_manager = DocumentManager(state)
pipeline = ReviewPipeline(state)

cliente = ollama.Client(host=OLLAMA_HOST)

try:
    models = cliente.list()
    modelos = [model['model'] for model in models.get('models', [])]
except Exception as e:
    print(f"Advertencia: no se pudo listar los modelos de Ollama: {e}")
    modelos = []

Color_alerta = {
    'rojo': '#e94560',
    'amarillo': '#e9c46a',
    'verde': '#06d6a0',
    'azul': '#4cc9f0'
}

# CONTROLADORES DE EVENTOS

def adjuntar_documento():
    """Abre el diálogo de archivo, copia el documento elegido y prepara la UI."""
    ruta = UIF.ask_open_file(
        "Seleccionar documento",
        "Documentos (*.pdf *.docx);;Todos los archivos (*.*)",
    )
    if not ruta:
        UIF.set_estado("Error al establecer la ruta del documento.", Color_alerta["rojo"])
        return

    src = Path(ruta)
    dest = PDF_DIR / src.name
    shutil.copy2(src, dest)

    state.pdf_path = dest
    state.pdf_name = DocumentManager.sanitizar_nombre(src.stem)
    state.extracted_text = None

    UIF.iniciar_display_derecho()
    UIF.set_lbl_archivo(src.name, Color_alerta["rojo"])
    UIF.escribir_salida(
        f"**Documento cargado**\n\nRuta: `{dest}`\n\nPresiona ▶ Iniciar Revisión para procesar."
    )
    UIF.reportar_etapa("preparado", 1.0)
    UIF.set_progreso(0)
    UIF.set_btn_iniciar_state(True)
    UIF.set_btn_procesar_texto_visible(False)


def iniciar_revision():
    """Valida las condiciones previas e inicia el proceso de revisión en segundo plano."""
    if state.is_busy():
        UIF.reportar_etapa("advertencia", 0.0, detalle="Proceso en curso; espera a que termine.")
        return
    if not state.has_document() and not state.has_extracted_text():
        UIF.reportar_etapa("advertencia", 0.0, detalle="Adjunta un documento primero.")
        return
    if state.selected_model is None:
        UIF.reportar_etapa("advertencia", 0.0, detalle="Selecciona un modelo primero.")
        return

    state.set_processing(True)
    UIF.set_modo_proceso(activo=True)
    UIF.reportar_etapa("iniciando", 0.0)

    threading.Thread(target=pipeline.ejecutar, daemon=True).start()


def interrumpir():
    """Interrumpe el proceso de revisión actual."""
    if state.is_busy():
        state.cancel()
        UIF.reportar_etapa("error", 0.0, detalle="Interrumpiendo proceso…")


def seleccionar_modelo(event=None):
    """Registra el modelo Ollama elegido y actualiza el display de modelo."""
    nombre = UIF.get_modelo_seleccionado()
    if not nombre:
        return
    state.selected_model = nombre
    if UIF.after_display and (state.has_document() or state.has_extracted_text()):
        UIF.reportar_etapa("preparado", 1.0)
        UIF.set_btn_iniciar_state(True)
    UIF.set_modelo_display(f"Modelo elegido: {nombre}", Color_alerta["verde"])


def abrir_revision(event):
    """Carga y muestra en pantalla la revisión seleccionada del historial."""
    from state import REVIEW_DIR
    nombre = UIF.get_historial_seleccion()
    if not nombre or nombre == "(sin revisiones)":
        return
    _mostrar_en_display(nombre, REVIEW_DIR / f"{nombre}.md", "Mostrando")


def abrir_texto(event):
    """Carga un texto extraído previamente para ser revisado de nuevo."""
    from state import TEXTOS_DIR
    nombre = UIF.get_texto_seleccionado()
    if not nombre or nombre == "(sin textos)":
        return
    ruta = TEXTOS_DIR / f"{nombre}.txt"
    contenido = _mostrar_en_display(nombre, ruta, "Mostrando texto", procesar_visible=True)
    if contenido is not None:
        state.extracted_text = contenido
        state.pdf_name = nombre


# HELPERS DE UI
def _mostrar_en_display(
    nombre: str, ruta: Path, etiqueta: str, procesar_visible: bool = False
) -> str | None:
    """Carga y muestra el contenido de un archivo en el panel de salida."""
    UIF.iniciar_display_derecho()
    if ruta.is_file():
        contenido = ruta.read_text(encoding="utf-8")
        UIF.escribir_salida(contenido)
        UIF.set_estado(f"{etiqueta}: {nombre[:45]}", "#06d6a0")
        UIF.set_btn_procesar_texto_visible(procesar_visible)
        return contenido
    return None


# INICIALIZACIÓN DE LA APLICACIÓN
UIF.wire_commands(
    on_adjuntar=adjuntar_documento,
    on_iniciar=iniciar_revision,
    on_stop=interrumpir,
    on_procesar_texto=iniciar_revision,
)

UIF.set_modelos(modelos)
if modelos:
    UIF.set_modelo_seleccionado(modelos[0])
    seleccionar_modelo()

UIF.conectar_seleccion_modelo(seleccionar_modelo)
UIF.conectar_seleccion_historial(abrir_revision)
UIF.conectar_seleccion_textos(abrir_texto)

UIF.cargar_historial()
UIF.cargar_textos()

UIF.ejecutar_app()
