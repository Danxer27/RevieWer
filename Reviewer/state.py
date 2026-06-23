"""
state.py - Gestión centralizada del estado de la aplicación RevieWer.

Centraliza todas las variables globales en una sola clase para evitar
race conditions, facilitar testing, y mejorar mantenibilidad.
"""

import threading
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Directorios y rutas de la aplicación
PDF_DIR = Path(__file__).parent / "pdfs"
REVIEW_DIR = Path(__file__).parent / "revisiones"
TEXTOS_DIR = Path(__file__).parent / "textos"
CHROMA_DIR = Path(__file__).parent / "dt/sira_chroma_db"

OLLAMA_HOST = 'http://localhost:11434'

# Asegurar existencia de directorios
PDF_DIR.mkdir(exist_ok=True)
REVIEW_DIR.mkdir(exist_ok=True)
TEXTOS_DIR.mkdir(exist_ok=True)

# LangSmith API
import os
os.environ['LANGCHAIN_TRACING_V2'] = 'true'
os.environ['LANGCHAIN_ENDPOINT'] = 'https://api.smith.langchain.com'
os.environ['LANGCHAIN_API_KEY'] = os.getenv("LANGCHAIN_API_KEY")



class RevisionState:
    """
    Clase que encapsula todo el estado de la aplicación.
    
    Atributos:
        pdf_path: Path al PDF cargado actualmente
        pdf_name: Nombre sanitizado del PDF
        is_processing: Flag que indica si hay un proceso de revisión en curso
        stop_event: threading.Event para interrumpir el proceso
        extracted_text: Texto extraído del PDF (cacheado para evitar re-extracciones)
        selected_model: Modelo Ollama seleccionado
        output_displayed: Flag interno de Interfaz (si se mostró el output)
    """
    
    def __init__(self):
        """Inicializa el estado con valores por defecto."""
        self.pdf_path: Optional[Path] = None
        self.pdf_name: Optional[str] = None
        self.is_processing: bool = False
        self.stop_event: threading.Event = threading.Event()
        self.extracted_text: Optional[str] = None
        self.selected_model: Optional[str] = None
        self.output_displayed: bool = False
        
    def reset(self) -> None:
        """
        Reinicia el estado a valores por defecto.
        Útil cuando se cancela un proceso o se inicia uno nuevo.
        """
        self.pdf_path = None
        self.pdf_name = None
        self.is_processing = False
        self.stop_event.clear()
        self.extracted_text = None
        self.output_displayed = False
        # Nota: selected_model se mantiene entre sesiones
        
    def is_busy(self) -> bool:
        """Retorna True si hay un proceso en curso."""
        return self.is_processing
    
    def cancel(self) -> None:
        """Señala que debe cancelarse el proceso actual."""
        self.stop_event.set()
        self.is_processing = False
    
    def set_processing(self, value: bool) -> None:
        """
        Actualiza el estado de procesamiento.
        Si se establece en False, limpia el evento de stop.
        """
        self.is_processing = value
        if not value:
            self.stop_event.clear()
    
    def has_document(self) -> bool:
        """Retorna True si hay un PDF cargado."""
        return self.pdf_path is not None
    
    def has_extracted_text(self) -> bool:
        """Retorna True si hay texto extraído en cache."""
        return self.extracted_text is not None
    
    def __repr__(self) -> str:
        """Representación en string para debugging."""
        return (
            f"RevisionState(pdf_path={self.pdf_path}, "
            f"is_processing={self.is_processing}, "
            f"selected_model={self.selected_model})"
        )
