import threading
import ollama
from typing import Union
from prompts import ESTRUCTURA, METODOLOGIA, REDACCION, SINTESIS


cliente = ollama.Client(host='http://localhost:11434')

AGENTES = {
    "estructura" : ESTRUCTURA,
    "metodologia" : METODOLOGIA,
    "redaccion" : REDACCION,
    "sintesis" : SINTESIS
}

def _correr_agente(nombre: str, modelo: str, texto: str, resultados: dict, errores: dict) -> Union[str, None]:
    
    try:
        respuesta = cliente.chat(
            model = modelo,
            messages = [
                {'role': 'system', 'content': AGENTES[nombre]},
                {'role': 'user', 'content': f"Documento a revisar:\n\n{texto}"}
            ],
            options = {'num_ctx': 32000, 'temperature': 0.2}
        )
        resultados[nombre] = respuesta['message']['content']
    except Exception as e:
        errores[nombre] = str(e)


def revisar_multiagente(texto: str, modelo: str, set_estado, set_progreso) -> Union[str, None]:
    resultados = {}
    errores = {}
    
    set_estado("Agentes analizando en paralelo...", "#4cc9f0")
    set_progreso(15)
    
    hilos = []
    
    #Los modelos corren al mismo tiempo
    for nombre in ["estructura", "metodologia", "redaccion"]:
        h = threading.Thread(
            target = _correr_agente,
            args = (nombre, modelo, texto, resultados, errores),
            daemon=True
        )
        hilos.append(h)
        h.start()
        
    #Espera a que los 3 terminen
    for h in hilos:
        h.join()
    
    if errores:
        set_estado(f"Error en agente: {list(errores.keys())}", "#e94560")
        return None
    
    set_progreso(70)
    
    set_estado("Sintetizando resultados...", "#4cc9f0")
    
    contexto_sintesis = f"""
    ## Revisión de Estructura:
    {resultados['estructura']}

    ---

    ## Revisión de Metodología:
    {resultados['metodologia']}

    ---

    ## Revisión de Redacción:
    {resultados['redaccion']}
    """
    try:
        respuesta_final = cliente.chat(
            model=modelo,
            messages=[
                {'role': 'system', 'content': AGENTES["sintesis"]},
                {'role': 'user',   'content': contexto_sintesis}
            ],
            options={'num_ctx': 32000, 'temperature': 0.2},
        )
        set_progreso(90)
        return respuesta_final['message']['content']

    except Exception as e:
        set_estado(f"Error en síntesis: {e}", "#e94560")
        return None

