import pytest

from app.tools import get_default_tools, get_tool, list_tools
from app.tools.base import ToolContext, ToolError
from app.tools.files import ReadFileTool, WriteFileTool
from app.tools.web_fetch import UNTRUSTED_CLOSE, UNTRUSTED_OPEN, html_to_text


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(run_id="test-run", workspace_dir=tmp_path)


def test_default_tools_registered():
    tools = get_default_tools()
    names = {t.name for t in tools}
    assert names == {"web_search", "web_fetch", "read_file", "write_file"}
    for tool in tools:
        assert tool.input_schema.get("type") == "object"
        assert tool.risk_level in ("safe", "sensitive", "dangerous")
        assert get_tool(tool.name) is tool
    assert len(list_tools()) >= 4


async def test_write_then_read(ctx):
    out = await WriteFileTool().run({"path": "informes/reporte.md", "content": "hola"}, ctx)
    assert "reporte.md" in out
    content = await ReadFileTool().run({"path": "informes/reporte.md"}, ctx)
    assert content == "hola"


@pytest.mark.parametrize("bad_path", ["../fuera.txt", "../../etc/passwd", "a/../../x"])
async def test_path_traversal_rejected(ctx, bad_path):
    with pytest.raises(ToolError, match="fuera del workspace"):
        await WriteFileTool().run({"path": bad_path, "content": "x"}, ctx)
    with pytest.raises(ToolError):
        await ReadFileTool().run({"path": bad_path}, ctx)


async def test_absolute_path_confined_to_workspace(ctx):
    # Un path "absoluto" se reinterpreta como relativo al workspace, no escapa.
    await WriteFileTool().run({"path": "/etc/dentro.txt", "content": "ok"}, ctx)
    assert (ctx.workspace_dir / "etc/dentro.txt").read_text() == "ok"


async def test_read_missing_file(ctx):
    with pytest.raises(ToolError, match="no existe"):
        await ReadFileTool().run({"path": "nada.txt"}, ctx)


def test_html_to_text_strips_scripts():
    text = html_to_text("<html><head><style>x{}</style></head><body><script>evil()</script><p>Hola  mundo</p></body></html>")
    assert text == "Hola mundo"


async def test_web_fetch_wraps_untrusted(ctx, monkeypatch):
    from app.tools import web_fetch as wf

    class FakeResponse:
        content = b"<p>dato externo</p>"
        encoding = "utf-8"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(wf.httpx, "AsyncClient", FakeClient)
    result = await wf.WebFetchTool().run({"url": "https://ejemplo.com"}, ctx)
    assert result.startswith(UNTRUSTED_OPEN)
    assert result.endswith(UNTRUSTED_CLOSE)
    assert "dato externo" in result


async def test_web_search_parses_results(ctx, monkeypatch):
    from app.tools import web_search as ws

    html_body = """
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpagina">T&iacute;tulo Uno</a>
    <a class="result__snippet" href="#">Un <b>fragmento</b> relevante</a>
    """

    class FakeResponse:
        text = html_body

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, data=None):
            return FakeResponse()

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    result = await ws.WebSearchTool().run({"query": "agentes"}, ctx)
    assert "Título Uno" in result
    assert "https://example.com/pagina" in result
    assert "fragmento relevante" in result


async def test_web_search_empty_query(ctx):
    from app.tools.web_search import WebSearchTool

    with pytest.raises(ToolError):
        await WebSearchTool().run({"query": "  "}, ctx)
