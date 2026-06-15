#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test suite para validar la reorganización del proyecto RevieWer.

Verifica que la nueva arquitectura de clases está correcta:
  - PromptEngine  en prompt_engine.py
  - DocumentManager en document.py
  - ReviewPipeline  en pipeline.py
  - reviewer.py como punto de entrada delgado
"""

import sys
import os
import ast


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _leer(fname: str) -> str:
    with open(fname, encoding="utf-8") as f:
        return f.read()


def _sintaxis_valida(fname: str) -> None:
    try:
        ast.parse(_leer(fname))
    except SyntaxError as e:
        raise AssertionError(f"SyntaxError en {fname}: {e}")


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

def test_state_module():
    """state.py se importa correctamente y su lógica funciona."""
    from state import RevisionState

    s = RevisionState()
    assert s.pdf_path is None
    assert s.pdf_name is None
    assert not s.is_processing
    assert not s.is_busy()
    assert not s.has_document()
    assert not s.has_extracted_text()

    s.set_processing(True)
    assert s.is_busy()

    s.cancel()
    assert not s.is_busy()

    s.extracted_text = "test"
    s.reset()
    assert s.extracted_text is None

    return True


def test_prompt_engine_exists():
    """prompt_engine.py existe y define la clase PromptEngine con la interfaz correcta."""
    assert os.path.exists("prompt_engine.py"), "prompt_engine.py no existe"
    _sintaxis_valida("prompt_engine.py")

    content = _leer("prompt_engine.py")

    assert "class PromptEngine" in content, "Falta class PromptEngine"
    assert "def completar_prompt" in content, "Falta método completar_prompt"
    assert "def _segmentar_paper" in content, "Falta método _segmentar_paper"
    assert "def _extraer_metodologia" in content, "Falta método _extraer_metodologia"
    assert "def _consultar_chroma" in content, "Falta método _consultar_chroma"
    assert "def _build_prompt" in content, "Falta método _build_prompt"
    assert "SECCIONES_REQUERIDAS" in content, "Falta constante SECCIONES_REQUERIDAS"

    return True


def test_document_manager_exists():
    """document.py existe y define la clase DocumentManager con la interfaz correcta."""
    assert os.path.exists("document.py"), "document.py no existe"
    _sintaxis_valida("document.py")

    content = _leer("document.py")

    assert "class DocumentManager" in content, "Falta class DocumentManager"
    assert "def extraer_texto" in content, "Falta método extraer_texto"
    assert "def guardar_reporte" in content, "Falta método guardar_reporte"
    assert "def guardar_texto_plano" in content, "Falta método guardar_texto_plano"
    assert "def sanitizar_nombre" in content, "Falta método sanitizar_nombre"

    return True


def test_pipeline_exists():
    """pipeline.py existe y define la clase ReviewPipeline con la interfaz correcta."""
    assert os.path.exists("pipeline.py"), "pipeline.py no existe"
    _sintaxis_valida("pipeline.py")

    content = _leer("pipeline.py")

    assert "class ReviewPipeline" in content, "Falta class ReviewPipeline"
    assert "def ejecutar" in content, "Falta método ejecutar"
    assert "def validar_reporte" in content, "Falta método validar_reporte"
    assert "def _ejecutar_llm" in content, "Falta método _ejecutar_llm"
    assert "def _obtener_texto" in content, "Falta método _obtener_texto"
    assert "DocumentManager" in content, "ReviewPipeline debe usar DocumentManager"
    assert "PromptEngine" in content, "ReviewPipeline debe usar PromptEngine"

    return True


def test_reviewer_is_slim():
    """reviewer.py es un punto de entrada delgado: sin lógica de negocio propia."""
    assert os.path.exists("reviewer.py"), "reviewer.py no existe"
    _sintaxis_valida("reviewer.py")

    content = _leer("reviewer.py")

    # Debe importar las nuevas clases
    assert "from document import DocumentManager" in content, "Falta import DocumentManager"
    assert "from pipeline import ReviewPipeline" in content, "Falta import ReviewPipeline"
    assert "from state import RevisionState" in content, "Falta import RevisionState"

    # Debe tener los event handlers de UI
    assert "def adjuntar_documento" in content, "Falta adjuntar_documento"
    assert "def iniciar_revision" in content, "Falta iniciar_revision"
    assert "def seleccionar_modelo" in content, "Falta seleccionar_modelo"
    assert "def interrumpir" in content, "Falta interrumpir"

    # NO debe contener lógica de negocio que fue delegada
    assert "def extraer_texto" not in content, \
        "extraer_texto no debe estar en reviewer.py (pertenece a DocumentManager)"
    assert "def _segmentar_paper" not in content, \
        "_segmentar_paper no debe estar en reviewer.py (pertenece a PromptEngine)"
    assert "def revisar_paper" not in content, \
        "revisar_paper no debe estar en reviewer.py (pertenece a ReviewPipeline)"

    # Wiring de UI presente
    assert "UIF.wire_commands" in content, "Falta wiring de comandos UI"
    assert "UIF.ejecutar_app" in content, "Falta llamada a ejecutar_app"

    return True


def test_old_files_removed():
    """Los archivos viejos fueron eliminados y no generan confusión."""
    removed = ["prompt.py", "construir_prompt.py", "modeling.py"]
    for fname in removed:
        assert not os.path.exists(fname), \
            f"{fname} todavía existe — debe ser eliminado para evitar importaciones duplicadas"
    return True


def test_all_syntax():
    """Todos los archivos nuevos tienen sintaxis Python válida."""
    files = [
        "prompt_engine.py",
        "document.py",
        "pipeline.py",
        "reviewer.py",
        "state.py",
        "interfaz.py",
    ]
    for fname in files:
        if os.path.exists(fname):
            _sintaxis_valida(fname)
    return True


def test_secciones_requeridas():
    """SECCIONES_REQUERIDAS tiene exactamente las 7 secciones esperadas (lectura textual)."""
    content = _leer("prompt_engine.py")

    secciones = [
        "# 1. Research Fingerprint",
        "# 2. Targeted Findings",
        "# 3. Cross-Section Issues",
        "# 4. Methodology Interrogation",
        "# 5. Reproducibility Audit",
        "# 6. Required Actions",
        "# 7. Final Verdict",
    ]
    for seccion in secciones:
        assert seccion in content, f"Sección faltante en prompt_engine.py: {seccion!r}"
    return True


# ─────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────

def main():
    tests = [
        ("State Module",             test_state_module),
        ("PromptEngine existe",       test_prompt_engine_exists),
        ("DocumentManager existe",    test_document_manager_exists),
        ("ReviewPipeline existe",     test_pipeline_exists),
        ("reviewer.py es slim",       test_reviewer_is_slim),
        ("Archivos viejos eliminados",test_old_files_removed),
        ("Sintaxis válida",           test_all_syntax),
        ("SECCIONES_REQUERIDAS",      test_secciones_requeridas),
    ]

    print("=" * 60)
    print("REORGANIZACIÓN TEST SUITE")
    print("=" * 60 + "\n")

    passed = failed = 0

    for test_name, test_fn in tests:
        try:
            test_fn()
            print(f"[OK]   {test_name}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {test_name}")
            print(f"       {e}")
            failed += 1
        except Exception as e:
            print(f"[FAIL] {test_name}")
            print(f"       Error inesperado: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Resultados: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("\n*** TODOS LOS TESTS PASARON — REORGANIZACIÓN EXITOSA ***\n")
        return 0
    else:
        print(f"\n[FAIL] {failed} test(s) fallaron\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
