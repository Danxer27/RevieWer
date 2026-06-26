# RevieWer

RevieWer es una herramienta de escritorio para la revisión automática de artículos académicos. Utiliza inteligencia artificial local para analizar documentos PDF, extraer texto y generar informes de revisión detallados.

## Funcionamiento

El sistema procesa documentos en varias etapas:

1. **Extracción de texto**: Convierte PDFs a texto plano utilizando bibliotecas como PyMuPDF.
2. **Análisis con IA**: Emplea modelos de lenguaje local (via Ollama) para evaluar coherencia, metodología, referencias y hallazgos.
3. **Generación de reporte**: Produce un informe en formato Markdown con análisis comparativo y resumen ejecutivo.
4. **Interfaz gráfica**: Una aplicación Qt (PySide6) permite subir archivos, seleccionar modelos y visualizar resultados.

## Tutorial

### Instalación
1. Instala Python 3.9-3.13 (la interfaz Qt requiere PySide6; Python 3.14 aún no es compatible).
2. Instala las dependencias: `pip install -r requirements.txt`.
3. Instala Ollama y descarga un modelo (ej: `ollama pull llama3`).

> En algunas maquinas se requerira estar ejectuando ollama en segundo plano en una terminal con el comando `& "C:\Users\your_user\AppData\Local\Programs\Ollama\ollama.exe" serve ` o la ruta donde este instalado Ollama.

### Uso
1. Ejecuta `python main.py`.
2. Selecciona un modelo de Ollama en la interfaz.
3. Haz clic en "Seleccionar PDF" y elige un archivo.
4. Presiona "Revisar" para iniciar el análisis.
5. Visualiza el reporte generado en la pestaña correspondiente.

![alt text](./Reviewer/imgs/ss_main_1.png)
