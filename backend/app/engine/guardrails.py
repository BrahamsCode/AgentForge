"""Guardrails de seguridad (Fase 4): política de aprobación y detección de riesgos.

Objetivo O5: ninguna herramienta ejecuta acciones destructivas sin política de
aprobación. La decisión es por nivel de riesgo de la herramienta, con posible
escalado si los argumentos disparan patrones sospechosos.
"""

import re

# Política por nivel de riesgo:
#   safe      → siempre se ejecuta
#   sensitive → se ejecuta salvo que dispare un patrón sospechoso
#   dangerous → siempre requiere aprobación humana
_DECISION_BY_RISK = {"safe": "allow", "sensitive": "allow", "dangerous": "ask"}

# Patrones que elevan una acción sensitive a "ask" (heurística conservadora).
_SUSPICIOUS = re.compile(
    r"\b(rm\s+-rf|sudo|shutdown|mkfs|:\(\)\s*\{|drop\s+table|truncate\s+table|"
    r"format\s+c:|DELETE\s+FROM|/etc/passwd|~/\.ssh|curl\s+[^|]*\|\s*sh)\b",
    re.IGNORECASE,
)


def evaluate_tool(tool, args: dict) -> tuple[str, str]:
    """Devuelve (decision, motivo). decision ∈ {"allow", "ask"}."""
    risk = getattr(tool, "risk_level", "safe")
    base = _DECISION_BY_RISK.get(risk, "ask")

    flat_args = " ".join(str(v) for v in args.values())
    if _SUSPICIOUS.search(flat_args):
        return "ask", f"patrón potencialmente destructivo en argumentos de {tool.name}"

    if base == "ask":
        return "ask", f"herramienta de riesgo '{risk}'"
    return "allow", ""


def scan_prompt_injection(text: str) -> list[str]:
    """Detecta intentos de inyección en contenido externo (marcado no confiable).

    Devuelve la lista de patrones encontrados; el motor los registra como aviso.
    El aislamiento real lo da el marcado <<CONTENIDO EXTERNO NO CONFIABLE>> +
    la instrucción del system prompt; esto es telemetría/defensa en profundidad.
    """
    patterns = [
        r"ignor(a|e|ar)\s+(las\s+)?(anteriores?\s+)?instrucciones",
        r"ignore\s+(all\s+)?(previous\s+)?instructions",
        r"disregard\s+(the\s+)?(above|previous)",
        r"system\s*prompt",
        r"nuevas?\s+instrucciones",
        r"you\s+are\s+now",
        r"actúa\s+como",
    ]
    found = []
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(pattern)
    return found
