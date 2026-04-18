import tkinter as tk
from tkinter import filedialog
import shutil
from pathlib import Path
import ollama
import os
import subprocess


# Carpeta donde se guardan los PDFs adjuntados
PDF_DIR = Path(__file__).parent / "pdfs"
PDF_DIR.mkdir(exist_ok=True)
MODELO_OL = "qwen3.5:4b"

pdf_actual = None  # ruta del PDF copiado, para que tu otro código la use
ruta_resultado = None

def adjuntar_pdf():
    global pdf_actual
    global ruta_resultado

    ruta = filedialog.askopenfilename(
        title="Seleccionar PDF",
        filetypes=[("Archivos PDF", "*.pdf")]
    )
    if not ruta:
        return

    src = Path(ruta)
    dest = PDF_DIR / src.name
    shutil.copy2(src, dest)
    pdf_actual = dest

    lbl_archivo.config(text=f"📄 {src.name}", fg="#e94560")
    salida.config(state="normal")
    salida.delete("1.0", "end")
    salida.insert("end", f"[PDF cargado]\nRuta: {dest}\n\nEsperando procesamiento...\n")
    salida.config(state="disabled")

    # Procesar pdf
    ruta_resultado = extraer_con_nougat(pdf_actual)
    if ruta_resultado:
        revisar_paper(ruta_markdown=ruta_resultado, modelo=MODELO_OL)
    else: 
        print("No se encontro la ruta del resultado o no se proceso correctamente.")


def extraer_con_nougat(ruta_pdf, carpeta_salida="textos_nougat"):
    # Nos aseguramos de que la carpeta exista
    if not os.path.exists(carpeta_salida):
        os.makedirs(carpeta_salida)
        
    print(f"Iniciando extracción profunda de: {ruta_pdf}...")
    print("Esto puede tardar un poco dependiendo de tu hardware...")
    
    # Construimos el comando de Nougat
    comando = [
        "nougat", 
        ruta_pdf, 
        "-o", carpeta_salida,
        "--no-skipping"
    ]
    
    # Ejecutamos el comando
    resultado = subprocess.run(comando, capture_output=True, text=True)
    
    # Verificamos que Python sí esté encontrando tu PDF antes de enviarlo a Nougat
    if not os.path.exists(ruta_pdf):
        print(f"El archivo {ruta_pdf} no existe en esa ruta.")
        return None

    if resultado.returncode == 0:
        print("Errores encontrados en nougat: ")
        print(resultado.stderr)
        print("================================")
        
        print("Archivos que existen en la carpeta de salida:")
        try:
            print(os.listdir(carpeta_salida))
        except Exception as e:
            print("No se pudo leer la carpeta:", e)
            
        nombre_base = os.path.splitext(os.path.basename(ruta_pdf))[0]
        ruta_resultado = os.path.join(carpeta_salida, f"{nombre_base}.mmd")
        
        if os.path.exists(ruta_resultado):
            print(f"¡Éxito! Texto extraído en: {ruta_resultado}")
            return ruta_resultado
        else:
            print(f"\nNougat generó el archivo {ruta_resultado}.")
            return None
    else:
        print("Hubo un error al procesar el documento.")
        print("Detalles del error:", resultado.stderr)
        return None



def escribir_salida(texto: str):
    salida.config(state="normal")
    salida.delete("1.0", "end")
    salida.insert("end", texto)
    salida.config(state="disabled")


def revisar_paper(ruta_markdown, modelo):
    #  Se le el archivo mmd que genera nougat
    if not os.path.exists(ruta_markdown):
        print(f"No se encontró el archivo: {ruta_markdown}")
        return
        
    print(f" Leyendo el documento: {ruta_markdown}...")
    with open(ruta_markdown, 'r', encoding='utf-8') as f:
        texto_paper = f.read()

    # Configuracion del prompt del modelo
    system_prompt = """
    Eres un revisor académico experto y riguroso ("Peer Reviewer") de una revista científica de alto impacto. 
    Tu trabajo es leer el documento proporcionado y generar un reporte de revisión estructurado.
    
    Debes evaluar:
    1. Resumen de la contribución principal (¿Qué problema resuelve?).
    2. Fortalezas del documento.
    3. Debilidades o áreas de mejora (metodología, claridad, resultados).
    4. Analisis Exahustivo de los procedimientos en las metodologias y experimentos
    4. Veredicto final: (Aceptar, Revisiones Menores, Revisiones Mayores, o Rechazar) con una breve justificación.
    
    Responde estrictamente en formato Markdown y mantén un tono profesional, objetivo y constructivo.
    """

    print(f" Enviando el texto a Ollama (Modelo: {modelo})... Esto puede tardar un poco.")
    
    # Hacemos la llamada a Ollama
    try:
        respuesta = ollama.chat(
            model=modelo,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"Aquí tienes el documento para revisar:\n\n{texto_paper}"}
            ],
            # TRUCO VITAL: Aumentar el contexto para que quepa todo el paper
            # 32000 tokens suelen ser suficientes para ~30 páginas. 
            options={
                'num_ctx': 32000, 
                'temperature': 0.2 # Temperatura baja para que sea analítico y no invente cosas (alucinaciones)
            }
        )
        
        # Mostramos y guardamos el resultado
        reporte = respuesta['message']['content']
        
        # print("\n" + "="*50)
        # print(" REPORTE DE REVISIÓN")
        # print("="*50 + "\n")
        # print(reporte)f
        escribir_salida(reporte)
        
        # Guardar el reporte en un archivo
        with open(f"reporte_revision.mmd", 'w', encoding='utf-8') as f:
            f.write(reporte)
            
    except Exception as e:
        print(f"Error al comunicarse con Ollama: {e}")


# ── UI ─────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("Adjuntor de PDF")
root.geometry("1024x756")
root.configure(bg="#1a1a2e")
root.resizable(False, False)

# Botón adjuntar
btn = tk.Button(
    root, text="➕  Adjuntar PDF",
    command=adjuntar_pdf,
    bg="#e94560", fg="white",
    font=("Consolas", 12, "bold"),
    relief="flat", padx=20, pady=10,
    cursor="hand2", activebackground="#c73652"
)
btn.pack(pady=(30, 10))

# Nombre del archivo cargado
lbl_archivo = tk.Label(
    root, text="Ningún archivo seleccionado",
    bg="#1a1a2e", fg="#4a4a8a",
    font=("Consolas", 10)
)
lbl_archivo.pack()

# Separador visual
tk.Frame(root, bg="#0f3460", height=1).pack(fill="x", padx=20, pady=16)

# Etiqueta de salida
tk.Label(
    root, text="Salida / Respuesta",
    bg="#1a1a2e", fg="#4a4a8a",
    font=("Consolas", 9)
).pack(anchor="w", padx=22)

# Recuadro de texto (salida)
frame_text = tk.Frame(root, bg="#0f3460", padx=2, pady=2)
frame_text.pack(fill="both", expand=True, padx=20, pady=(4, 20))

salida = tk.Text(
    frame_text,
    bg="#0d0d1a", fg="#dde1e7",
    font=("Consolas", 10),
    relief="flat", wrap="word",
    state="disabled",
    insertbackground="white",
    padx=10, pady=8
)
scrollbar = tk.Scrollbar(frame_text, command=salida.yview)
salida.config(yscrollcommand=scrollbar.set)
scrollbar.pack(side="right", fill="y")
salida.pack(fill="both", expand=True)

root.mainloop()