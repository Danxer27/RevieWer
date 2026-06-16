"""
pipeline.py — Pipeline de revisión de papers en RevieWer.

Responsabilidad única: orquestar el proceso completo de revisión,
desde la obtención del texto hasta el guardado del reporte.

Integra DocumentManager (E/S) y PromptEngine (construcción del prompt)
para ejecutar el ciclo completo de revisión con streaming al LLM.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

import interfaz as UIF
from state import OLLAMA_HOST, RevisionState
from document import DocumentManager
from prompt_engine import PromptEngine, SECCIONES_REQUERIDAS


class ReviewPipeline:
    """
    Orquesta el pipeline completo de revisión de un paper académico.

    Etapas:
      1. Obtener texto (desde caché o extrayendo del documento).
      2. Construir el prompt con PromptEngine.
      3. Enviar al LLM con streaming y mostrar tokens en la UI.
      4. Validar la estructura del reporte generado.
      5. Guardar el reporte y el texto extraído en disco.
      6. Actualizar la UI al finalizar.

    Uso típico:
        pipeline = ReviewPipeline(state)
        pipeline.ejecutar()        # llamar desde un hilo separado
    """

    def __init__(self, state: RevisionState) -> None:
        self._state = state
        self._doc = DocumentManager(state)
        self._prompt_engine = PromptEngine()

    # Etapas individuales

    def _obtener_texto(self) -> str | None:
        """
        Retorna el texto a revisar.

        Si ya hay texto cacheado en el estado lo usa directamente;
        de lo contrario lo extrae del documento adjunto.
        """
        if self._state.has_extracted_text():
            UIF.reportar_etapa("extraccion_texto", 1.0)
            return self._state.extracted_text

        UIF.reportar_etapa("extraccion_texto", 0.0)
        texto = self._doc.extraer_texto(str(self._state.pdf_path))
        if not texto:
            UIF.reportar_error("No se pudo extraer texto del documento.")
            UIF.escribir_salida("**Error:** el documento no contiene texto extraíble.")
            return None

        UIF.reportar_etapa("extraccion_texto", 1.0)
        return texto

    def validar_reporte(self, reporte: str) -> tuple[bool, list[str]]:
        """
        Verifica que el reporte contenga todas las secciones requeridas.

        Returns:
            (es_valido, secciones_faltantes)
        """
        faltantes = [s for s in SECCIONES_REQUERIDAS if s not in reporte]
        return len(faltantes) == 0, faltantes

    def _ejecutar_llm(self, texto: str) -> str | None:
        """
        Construye el prompt, envía al LLM con streaming y acumula el reporte.

        Returns:
            El reporte completo como string, o None si fue cancelado o falló.
        """
        UIF._buffer.clear()
        UIF.escribir_salida("_Generando revisión..._")

        UIF.reportar_etapa("revision", 0.0)
        reporte_completo: list[str] = []
        inicio, fin = UIF.ETAPAS["revision"]["progreso"]
        progreso_actual = float(inicio)

        llm = ChatOllama(
            model=self._state.selected_model,
            base_url=OLLAMA_HOST,
            temperature=0,
            num_ctx=32000,
            seed=42,
            top_k=1,
            top_p=1.0,
            num_predict=4096,
        )

        # Pasar el LLM a completar_prompt para que ChecklistRAG
        # pueda usar HyDE y Multi-Query con el mismo modelo del usuario.
        system_prompt = self._prompt_engine.completar_prompt(texto=texto, llm=llm)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Here is the paper to review:\n\n{texto}"),
        ]

        try:
            for chunk in llm.stream(messages):
                if self._state.stop_event.is_set():
                    return None

                token = chunk.content or ""
                if not token:
                    continue

                reporte_completo.append(token)
                UIF.append_salida(token)
                progreso_actual = min(float(fin) - 1, progreso_actual + 0.04)
                UIF.set_progreso(int(progreso_actual))

            UIF.reportar_etapa("revision", 1.0)
            return "".join(reporte_completo)

        except Exception as e:
            UIF.reportar_error(f"Error al comunicarse con Ollama: {e}")
            UIF.escribir_salida(f"**Error al comunicarse con Ollama:**\n\n{e}")
            return None

    # Pipeline principal

    def ejecutar(self) -> None:
        """
        Ejecuta el pipeline completo de revisión.

        Diseñado para correr en un hilo separado (daemon).
        Comprueba el stop_event entre etapas para soportar cancelación limpia.
        """
        try:
            # Etapa 1: Obtener texto
            if self._state.stop_event.is_set():
                return self._cancelado()
            texto = self._obtener_texto()
            if not texto:
                return

            # Etapa 2: Generar reporte con el LLM
            if self._state.stop_event.is_set():
                return self._cancelado()
            reporte = self._ejecutar_llm(texto)
            if reporte is None:
                return self._cancelado()

            # Etapa 3: Validar estructura del reporte
            es_valido, faltantes = self.validar_reporte(reporte)
            if not es_valido:
                UIF.reportar_etapa(
                    "advertencia",
                    0.5,
                    detalle=f"Reporte incompleto: faltan {', '.join(faltantes)}",
                )
                reporte += f"\n\n---\n **Secciones no generadas:** {', '.join(faltantes)}"

            # Etapa 4: Guardar resultados
            UIF.reportar_etapa("guardando", 0.0)
            self._doc.guardar_reporte(reporte)

            texto_era_cacheado = self._state.has_extracted_text()
            if not texto_era_cacheado:
                self._doc.guardar_texto_plano(texto)

            # Etapa 5: Finalizar y actualizar UI
            UIF._finalizar_streaming()
            UIF.reportar_etapa("guardando", 1.0)
            UIF.reportar_etapa("completado", 1.0)
            UIF.cargar_historial()
            self._state.extracted_text = None

        except Exception as e:
            UIF.reportar_error(str(e))
            UIF.escribir_salida(f"**Error inesperado:**\n\n{e}")
        finally:
            self._restaurar_botones()

    # Helpers de control

    def _restaurar_botones(self) -> None:
        """Restaura el estado de los botones al terminar o interrumpir un proceso."""
        self._state.set_processing(False)
        UIF.set_modo_proceso(activo=False)

    def _cancelado(self) -> None:
        """Maneja la cancelación limpia de un proceso de revisión."""
        UIF.reportar_error("Proceso interrumpido.")
        UIF._buffer.clear()
        self._restaurar_botones()
