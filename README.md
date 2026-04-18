# RevieWer
Es un sistema de revisión académica de papers basado en una arquitectura multi-agente de IA que automatiza el proceso de revisar articulos cientificos antes de su envio.\
El usuario sube un paper en PDF o Word, y el sistema lo procesa en cinco etapas:


- [x] **Extracción** — procesa el documento y obtiene texto estructurado, metadatos y secciones.
- [1/2] **Análisis** — agentes especializados evalúan coherencia, metodología, referencias y hallazgos, coordinados por un orquestador que corre sobre un modelo de lenguaje local vía Ollama.
- [ ] **Contextualización** — consulta bases de datos académicas externas como  para encontrar papers similares y posibles contraargumentos.
- [ ] **Anotación** — el usuario puede añadir sus propias notas al reporte generado.
- [x] **Salida** — genera un reporte exportable en con modo comparativo y resumen ejecutivo.

## Versiones

1. [Version Preeliminar (Nougat) ](#Nougat_Version)
2. [Version 1.0](#instalación)
3. [Version 1.0 (Joel)](#uso)

## Nougat_Version
La version Nougat es una version previa del revisor donde procesa el texto mediante NOUGAT siendo una herramienta de Meta basada en Deep Learning para escanear a profundidad documentos, esto requiere mucho poder computacional y esta sujeto a errores de extraccion ocasionados por formato y decoraciones en los articulos.

  >Esta version requiere ejecutarse con Python 3.11 e instalar las librerias con las versiones especificadas en el 
`requirements.txt`

## Review_1
Esta es la version que fue disenada para poder extraer texto plano de manera mas eficaz en papers aun no formateados. Esta version es mas ligera a la hora de extraer texto de los documentos antes de pasarlo por los LLMs para su revision.
> Puede ejecutarse en versiones de `python 3.9 - 3.14` siempre y cuando tenga las librerias correspondientes instaladas.

## Reviwer_1 (Joel)