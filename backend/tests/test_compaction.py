"""Tests de la compresión de contexto (ToolCallingSession.compact)."""

from app.llm.toolcalling import ToolCallingSession


def _session_with_history(provider: str, n_old: int, big: str) -> ToolCallingSession:
    s = ToolCallingSession(provider=provider, model="m", system_prompt="sys", tools=[])
    for i in range(n_old):
        if provider == "anthropic":
            s._messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"c{i}", "name": "t", "input": {}}]})
            s._messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": f"c{i}", "content": big, "is_error": False}],
            })
        else:
            s._messages.append({"role": "assistant", "content": "llamo herramienta"})
            s._messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": big})
    return s


def test_compact_truncates_old_anthropic_tool_results():
    big = "x" * 10_000
    s = _session_with_history("anthropic", n_old=8, big=big)
    truncated = s.compact(keep_last=4, max_chars=1000)

    assert truncated == 6  # 8 resultados, los 2 últimos quedan en keep_last=4 mensajes
    old = s._messages[1]["content"][0]["content"]
    assert len(old) < 2000
    assert "comprimido" in old
    # Los recientes intactos
    assert s._messages[-1]["content"][0]["content"] == big
    # Los mensajes assistant no se tocan
    assert s._messages[0]["content"][0]["type"] == "tool_use"


def test_compact_truncates_old_openai_tool_messages():
    big = "y" * 5_000
    s = _session_with_history("openai", n_old=6, big=big)
    truncated = s.compact(keep_last=2, max_chars=800)
    assert truncated == 5
    assert len(s._messages[2]["content"]) < 1600
    assert s._messages[-1]["content"] == big


def test_compact_noop_on_short_history():
    s = _session_with_history("anthropic", n_old=2, big="corto")
    assert s.compact(keep_last=6) == 0
