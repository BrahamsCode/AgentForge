import math

import pytest

from app.memory.chunking import chunk_text
from app.memory.embeddings import HashEmbedder


def test_chunk_empty_and_short():
    assert chunk_text("") == []
    assert chunk_text("   ") == []
    assert chunk_text("Hola mundo.") == ["Hola mundo."]


def test_chunk_respects_max_chars_and_no_word_split():
    text = " ".join(f"palabra{i}" for i in range(2000))
    chunks = chunk_text(text, max_chars=500, overlap=50)
    assert all(len(c) <= 500 for c in chunks)
    # No parte palabras: cada chunk empieza/termina en palabra completa
    vocabulary = set(text.split())
    for chunk in chunks:
        words = chunk.split()
        assert words[0] in vocabulary
        assert words[-1] in vocabulary
    # Todo el contenido está cubierto
    assert vocabulary == {w for c in chunks for w in c.split()}


def test_chunk_overlap_present():
    sentences = ". ".join(f"Oración número {i} con contenido" for i in range(100)) + "."
    chunks = chunk_text(sentences, max_chars=300, overlap=80)
    assert len(chunks) > 1
    # Algún solape: el inicio del chunk i+1 aparece al final del chunk i
    overlaps = sum(
        1 for a, b in zip(chunks, chunks[1:]) if b.split()[0] in a.split()[-20:]
    )
    assert overlaps > 0


async def test_hash_embedder_properties():
    embedder = HashEmbedder()
    [v1] = await embedder.embed(["los agentes coordinan tareas"])
    [v2] = await embedder.embed(["los agentes coordinan tareas"])
    [v3] = await embedder.embed(["texto completamente distinto sobre cocina"])

    assert len(v1) == 1024
    assert v1 == v2  # determinista
    assert v1 != v3
    assert abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-9  # normalizado L2


async def test_hash_embedder_empty_text():
    [v] = await HashEmbedder().embed([""])
    assert len(v) == 1024
    assert math.sqrt(sum(x * x for x in v)) == pytest.approx(1.0)


def test_search_memory_tool_contract():
    from app.memory.tool import build_search_memory_tool

    tool = build_search_memory_tool()
    assert tool.name == "search_memory"
    assert tool.risk_level == "safe"
    assert tool.input_schema["type"] == "object"
    assert "query" in tool.input_schema["properties"]
