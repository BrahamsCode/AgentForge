"""Tests de la herramienta browser (backlog v2).

Por defecto NO dependen de un navegador real (puede no haber display ni el
paquete pip ``playwright`` instalado). Se prueba la lógica pura:
input_schema, validación de argumentos y metadatos de la Tool. Hay UN test
opcional que se salta si playwright no está o si el navegador no arranca en el
entorno.
"""

import pathlib

import pytest

from app.tools.base import ToolContext, ToolError
from app.tools.browser import (
    UNTRUSTED_CLOSE,
    UNTRUSTED_OPEN,
    BrowserTool,
    _validate,
    build_input_schema,
)


def test_metadata():
    tool = BrowserTool()
    assert tool.name == "browser"
    assert tool.risk_level == "sensitive"
    assert tool.timeout_seconds == 60


def test_input_schema_is_valid_object_with_action_enum():
    schema = build_input_schema()
    assert schema["type"] == "object"
    assert schema["required"] == ["action"]
    enum = schema["properties"]["action"]["enum"]
    assert set(enum) == {"goto", "click", "type", "extract_text", "screenshot"}
    # La Tool expone el mismo schema.
    assert BrowserTool.input_schema["properties"]["action"]["enum"] == enum


def test_validate_accepts_valid_args():
    _validate("goto", {"url": "https://example.com"})
    _validate("click", {"selector": "#btn"})
    _validate("type", {"selector": "#in", "text": "hola"})
    _validate("extract_text", {})
    _validate("screenshot", {})


def test_validate_rejects_unknown_action():
    with pytest.raises(ToolError):
        _validate("scroll", {})


@pytest.mark.parametrize(
    "action,args",
    [
        ("goto", {}),  # falta url
        ("goto", {"url": "   "}),  # url en blanco
        ("click", {}),  # falta selector
        ("type", {"selector": "#in"}),  # falta text
        ("type", {"text": "hola"}),  # falta selector
    ],
)
def test_validate_rejects_missing_required_args(action, args):
    with pytest.raises(ToolError):
        _validate(action, args)


@pytest.mark.asyncio
async def test_run_rejects_missing_args_before_touching_browser(tmp_path):
    tool = BrowserTool()
    ctx = ToolContext(run_id="r-noargs", workspace_dir=tmp_path)
    with pytest.raises(ToolError):
        await tool.run({"action": "goto"}, ctx)


@pytest.mark.asyncio
async def test_extract_text_from_local_file(tmp_path):
    """Test opcional real: requiere playwright + navegador funcional.

    Usa un archivo HTML local (file://) — sin red. Si playwright no está
    instalado o el navegador no arranca en el entorno, se salta.
    """
    pytest.importorskip("playwright")

    from app.tools import browser as browser_mod

    html = tmp_path / "page.html"
    html.write_text(
        "<html><body><h1>Hola Mundo</h1><p>Contenido de prueba</p></body></html>",
        encoding="utf-8",
    )
    url = pathlib.Path(html).as_uri()

    tool = BrowserTool()
    ctx = ToolContext(run_id="r-browser-test", workspace_dir=tmp_path)
    try:
        goto_result = await tool.run({"action": "goto", "url": url}, ctx)
        assert "Navegado" in goto_result
        text = await tool.run({"action": "extract_text"}, ctx)
    except ToolError as exc:
        pytest.skip(f"Navegador no disponible en el entorno: {exc}")
    finally:
        await browser_mod.close_browser(ctx.run_id)

    assert UNTRUSTED_OPEN in text
    assert UNTRUSTED_CLOSE in text
    assert "Hola Mundo" in text
    assert "Contenido de prueba" in text
