from Promt import promt as PROMT
from datetime import datetime
import Interfaz as UIF
from langchain_ollama import ChatOllama


def revisar_paper(texto: str, MODELO_OL: str):
    system_prompt = PROMT

    UIF.set_estado("Generando revisión...", "#4cc9f0")
    UIF.set_progreso(20)
    UIF._buffer.clear()

    # Mostrar indicador de carga inicial
    UIF._ui(lambda: UIF.salida_html.load_html(UIF._md_a_html("_Generando revisión..._")))

    reporte_completo = []
    progreso_actual  = 20.0

    try:
        stream = ChatOllama(
            model=MODELO_OL,
            base_url="http://localhost:11434",
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user',   'content': f"Aquí tienes el documento para revisar:\n\n{texto}"}
            ],
            options={
                'num_ctx': 32000,
                'temperature': 0,
                'seed': 42,         
                'top_k': 1,         
                'top_p': 1.0,
                'num_predict': 4096,
            },
            stream=True,
        )

        for chunk in stream:
            # if stop_event.is_set():
            #     return None
            token = chunk['message']['content']
            reporte_completo.append(token)
            UIF.append_salida(token)
            progreso_actual = min(95.0, progreso_actual + 0.05)
            UIF.set_progreso(int(progreso_actual))

        output = str(datetime.now().strftime("%d%m%y %H%M")) + f' Modelo: {MODELO_OL}\n'
        return output.join(reporte_completo)

    except Exception as e:
        UIF.set_estado(f"Error Ollama: {e}", "#e94560")
        UIF.escribir_salida(f"**Error al comunicarse con Ollama:**\n\n{e}")