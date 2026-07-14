"""Herramientas de comunicación directa entre agentes (v2).

Permiten que sub-agentes de un mismo run se envíen mensajes sin pasar por el
orquestador. La identidad del emisor y los destinatarios válidos vienen del
ToolContext (agent_name / roster), que el motor rellena por tarea.
"""

import uuid


def build_messaging_tools() -> list:
    from app.tools.base import Tool, ToolContext, ToolError

    class SendMessageTool(Tool):
        name = "send_message"
        description = (
            "Envía un mensaje directo a otro agente de tu equipo (o 'all' para difundirlo). "
            "Úsalo para pedir ayuda, pasar un hallazgo o coordinarte sin esperar al orquestador."
        )
        input_schema = {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Nombre del agente destinatario o 'all'"},
                "content": {"type": "string", "description": "Contenido del mensaje"},
            },
            "required": ["to", "content"],
        }
        risk_level = "safe"
        timeout_seconds = 15

        async def run(self, args: dict, ctx: ToolContext) -> str:
            to = str(args.get("to", "")).strip()
            content = str(args.get("content", "")).strip()
            if not to or not content:
                raise ToolError("Debes indicar 'to' y 'content'")
            if to != "all" and to not in ctx.roster:
                disponibles = ", ".join(ctx.roster) or "(ninguno)"
                raise ToolError(
                    f"Destinatario desconocido: {to!r}. Agentes disponibles: {disponibles}"
                )

            from app.db import SessionLocal
            from app.models import AgentMessage

            async with SessionLocal() as db:
                db.add(
                    AgentMessage(
                        run_id=uuid.UUID(ctx.run_id),
                        from_agent_id=uuid.UUID(ctx.agent_id) if ctx.agent_id else None,
                        from_agent_name=ctx.agent_name or "desconocido",
                        to_agent=to,
                        content=content,
                    )
                )
                await db.commit()
            destino = "todo el equipo" if to == "all" else to
            return f"Mensaje enviado a {destino}."

    class CheckMessagesTool(Tool):
        name = "check_messages"
        description = (
            "Revisa tu bandeja: mensajes que otros agentes te enviaron (directos o difusiones). "
            "Los marca como leídos."
        )
        input_schema = {"type": "object", "properties": {}}
        risk_level = "safe"
        timeout_seconds = 15

        async def run(self, args: dict, ctx: ToolContext) -> str:
            from sqlalchemy import or_, select

            from app.db import SessionLocal
            from app.models import AgentMessage

            me = ctx.agent_name or ""
            async with SessionLocal() as db:
                rows = list(
                    await db.scalars(
                        select(AgentMessage)
                        .where(
                            AgentMessage.run_id == uuid.UUID(ctx.run_id),
                            AgentMessage.read.is_(False),
                            AgentMessage.from_agent_name != me,
                            or_(AgentMessage.to_agent == me, AgentMessage.to_agent == "all"),
                        )
                        .order_by(AgentMessage.created_at)
                    )
                )
                if not rows:
                    return "No tienes mensajes nuevos."
                for message in rows:
                    message.read = True
                await db.commit()
                lines = [
                    f"- De {m.from_agent_name}"
                    + (" (difusión)" if m.to_agent == "all" else "")
                    + f": {m.content}"
                    for m in rows
                ]
            return "Mensajes nuevos:\n" + "\n".join(lines)

    return [SendMessageTool(), CheckMessagesTool()]
