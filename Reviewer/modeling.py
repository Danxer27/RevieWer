import Interfaz as UIF
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from Construir_promt import completar_promt


def revisar_paper(texto: str, MODELO_OL: str) -> str | None:
    UIF._buffer.clear()
    UIF._ui(lambda: UIF.salida_html.load_html(UIF._md_a_html("_Generando revisión..._")))

    system_prompt = completar_promt(texto=texto)

    UIF.reportar_etapa("revision", 0.0)
    reporte_completo = []
    inicio, fin = UIF.ETAPAS["revision"]["progreso"]
    progreso_actual = float(inicio)

    llm = ChatOllama(
        model=MODELO_OL,
        base_url="http://localhost:11434",
        temperature=0,
        num_ctx=32000,
        seed=42,
        top_k=1,
        top_p=1.0,
        num_predict=4096,
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Aquí tienes el documento para revisar:\n\n{texto}"),
    ]

    try:
        for chunk in llm.stream(messages):
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
