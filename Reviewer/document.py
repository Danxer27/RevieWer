"""
document.py — Gestión de documentos y archivos en RevieWer.

Responsabilidad única: operaciones de lectura y escritura de archivos.

  - Extracción de texto de PDF y DOCX.
  - Sanitización de nombres de archivo.
  - Guardado de reportes Markdown.
  - Guardado del texto extraído en disco.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Union

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # PyMuPDF

from docx import Document

import interfaz as UIF
from state import REVIEW_DIR, TEXTOS_DIR, RevisionState


class DocumentManager:
    """
    Maneja todas las operaciones de lectura y escritura de archivos de RevieWer.

    Uso típico:
        dm = DocumentManager(state)
        texto = dm.extraer_texto("/ruta/al/paper.pdf")
        dm.guardar_reporte(reporte)
    """

    def __init__(self, state: RevisionState) -> None:
        self._state = state

    # ── Lectura de documentos ─────────────────────────────────────────────

    def extraer_texto(self, ruta_archivo: str) -> Union[str, None]:
        """
        Extrae el texto plano de un PDF o DOCX.

        Returns:
            El texto extraído, o None si falla o el documento está vacío.
        """
        ruta = Path(ruta_archivo)

        if ruta.suffix.lower() == ".pdf":
            return self._leer_pdf(ruta)

        if ruta.suffix.lower() == ".docx":
            return self._leer_docx(ruta)

        print(f"Formato no soportado: {ruta.suffix}")
        return None

    def _leer_pdf(self, ruta: Path) -> str | None:
        """Lee y concatena el texto de todas las páginas de un PDF."""
        try:
            doc = fitz.open(str(ruta))
            texto = "\n\n".join(page.get_text() for page in doc)
            doc.close()
            return texto if texto.strip() else None
        except Exception as e:
            print(f"Error al leer el pdf: {e}")
            return None

    def _leer_docx(self, ruta: Path) -> str | None:
        """Lee y concatena los párrafos con contenido de un DOCX."""
        try:
            doc = Document(str(ruta))
            texto = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return texto if texto.strip() else None
        except Exception as e:
            print(f"Error al leer DOCX: {e}")
            return None

    # ── Escritura de archivos ─────────────────────────────────────────────

    def guardar_reporte(self, reporte: str) -> None:
        """Persiste el reporte Markdown en disco con encabezado de metadatos."""
        ruta_md = self._ruta_sin_colision(REVIEW_DIR, self._state.pdf_name, ".md")
        with open(ruta_md, "w", encoding="utf-8") as f:
            f.write(f"# Revisión: {self._state.pdf_name}\n")
            f.write(f"_Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n")
            f.write(f"_Modelo: {self._state.selected_model}_\n\n")
            f.write(reporte)

    def guardar_texto_plano(self, texto: str) -> None:
        """Guarda el texto extraído en disco y actualiza el panel de textos en la UI."""
        ruta_txt = TEXTOS_DIR / f"{self._state.pdf_name}.txt"
        with open(ruta_txt, "w", encoding="utf-8") as f:
            f.write(texto)
        UIF.cargar_textos()

    # ── Utilidades de nombres ─────────────────────────────────────────────

    @staticmethod
    def sanitizar_nombre(name: str) -> str:
        """Limpia y normaliza un nombre de archivo para uso seguro en el sistema."""
        name = unicodedata.normalize("NFD", name)
        name = name.encode("ascii", "ignore").decode()
        name = re.sub(r"[^\w\s-]", "", name)
        name = re.sub(r"\s+", "_", name.strip())
        return name.lower()

    @staticmethod
    def _ruta_sin_colision(directorio: Path, nombre: str, extension: str) -> Path:
        """Genera una ruta única añadiendo un contador si ya existe el archivo."""
        ruta = directorio / f"{nombre}{extension}"
        contador = 1
        while ruta.exists():
            ruta = directorio / f"{nombre}({contador}){extension}"
            contador += 1
        return ruta
