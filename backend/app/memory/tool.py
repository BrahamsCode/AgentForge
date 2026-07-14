"""Herramienta search_memory: RAG sobre la memoria de largo plazo."""


def build_search_memory_tool():
    from app.tools.base import Tool, ToolContext, ToolError

    class SearchMemoryTool(Tool):
        name = "search_memory"
        description = (
            "Busca en la memoria de largo plazo (documentos subidos y aprendizajes "
            "previos) por similitud semántica. Úsala antes de buscar en la web si "
            "el conocimiento puede estar ya en la base."
        )
        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Consulta semántica"},
                "limit": {"type": "integer", "description": "Máx. resultados (default 5)"},
            },
            "required": ["query"],
        }
        risk_level = "safe"
        timeout_seconds = 30

        async def run(self, args: dict, ctx: ToolContext) -> str:
            query = str(args.get("query", "")).strip()
            if not query:
                raise ToolError("El argumento 'query' es obligatorio")
            limit = min(int(args.get("limit") or 5), 20)

            from app.db import SessionLocal
            from app.memory.embeddings import get_embedder
            from app.memory.service import search_memory

            async with SessionLocal() as db:
                results = await search_memory(
                    db, query=query, embedder=get_embedder(), limit=limit
                )
            if not results:
                return "La memoria no contiene nada relevante para esa consulta."
            return "\n".join(
                f"{i + 1}. [{r['document_name']}#{r['chunk_index']} · score {r['score']}] "
                f"{r['content'][:500]}"
                for i, r in enumerate(results)
            )

    return SearchMemoryTool()
