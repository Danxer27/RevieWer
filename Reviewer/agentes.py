import threading
import ollama
from typing import Union
from prompts import ESTRUCTURA, METODOLOGIA, REDACCION, SINTESIS
from context import obtener_contexto

cliente = ollama.Client(host='http://localhost:11434')
USAR_OPENALEX = True

AGENTES = {
    "estructura" : ESTRUCTURA,
    "metodologia" : METODOLOGIA,
    "redaccion" : REDACCION,
    "sintesis" : SINTESIS
}

def _correr_agente(nombre: str, modelo: str, texto: str, resultados: dict, errores: dict, contexto_arte: str="") -> Union[str, None]:
    
    try:
        # Armar contenido con o sin contexto de OpenAlex
        contenido = f"Document to review:\n\n{texto}"
        if contexto_arte:
            contenido = f"{contenido}\n\n---\n\nRelated literature from OpenAlex (use this to compare and contextualize your assessment):\n\n{contexto_arte}"  # contexto después
        respuesta = cliente.chat(
            model = modelo,
            messages = [
                {'role': 'system', 'content': AGENTES[nombre]},
                {'role': 'user', 'content': contenido}
            ],
            options = {'num_ctx': 32000, 'temperature': 0.0}
        )
        resultados[nombre] = respuesta['message']['content']
    except Exception as e:
        errores[nombre] = str(e)


def revisar_multiagente(texto: str, modelo: str, set_estado, set_progreso) -> Union[str, None]:
    
    
    if USAR_OPENALEX:
        set_estado("Consultando estado del arte...", "#4cc9f0")
        contexto_arte = obtener_contexto(texto)
    else:
        contexto_arte = ""
    
    
    print(f"=== CONTEXTO OPENALEX ===")
    print(contexto_arte[:500] if contexto_arte else "VACÍO")
    print("=== FIN ===")
    
    
    resultados = {}
    errores = {}
    
    set_estado("Agentes analizando en paralelo...", "#4cc9f0")
    set_progreso(15)
    
    hilos = []
    
    #Los modelos corren al mismo tiempo
    for nombre in ["estructura", "metodologia", "redaccion"]:
        h = threading.Thread(
            target = _correr_agente,
            args = (nombre, modelo, texto, resultados, errores, contexto_arte),
            daemon=True
        )
        hilos.append(h)
        h.start()
        
    #Espera a que los 3 terminen
    for h in hilos:
        h.join()
    
    if errores:
        print(f"=== ERRORES EN AGENTES ===")
        print(errores)  # ← agrega esto
        print("=== FIN ===")
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

