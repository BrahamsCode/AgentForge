"""Plantillas de equipo preconfiguradas (builtin) del marketplace.

Cada entrada es un dict con name/description/category/spec, alineada con los
casos de uso de referencia del diseño (CU-1 investigación, CU-2 análisis de
datos, CU-3 monitoreo). `seed_builtins` las materializa como TeamTemplate con
is_builtin=True.

Modelos por defecto: orquestadores en `claude-opus-4-8`, miembros en
`claude-sonnet-5`.
"""

ORCHESTRATOR_MODEL = "claude-opus-4-8"
MEMBER_MODEL = "claude-sonnet-5"

BUILTIN_TEMPLATES: list[dict] = [
    {
        "name": "Investigación profunda",
        "description": (
            "Equipo para investigación de mercado y síntesis: un orquestador "
            "coordina dos investigadores en paralelo, un analista sintetiza y un "
            "redactor entrega un informe en Markdown con tablas comparativas."
        ),
        "category": "research",
        "spec": {
            "orchestrator": {
                "name": "Coordinador de investigación",
                "role": "orchestrator",
                "model_provider": "anthropic",
                "model_name": ORCHESTRATOR_MODEL,
                "system_prompt": (
                    "Eres el orquestador de un equipo de investigación. Planifica la "
                    "tarea, delega búsquedas a los investigadores en paralelo, pide al "
                    "analista que sintetice los hallazgos y al redactor que produzca el "
                    "informe final. Verifica cobertura y calidad antes de entregar."
                ),
                "max_steps": 40,
                "max_cost_usd": 3.0,
            },
            "members": [
                {
                    "name": "Investigador A",
                    "role": "researcher",
                    "model_provider": "anthropic",
                    "model_name": MEMBER_MODEL,
                    "system_prompt": (
                        "Eres un investigador. Busca en la web fuentes relevantes y "
                        "fiables, extrae datos concretos con citas y resume hallazgos "
                        "de forma estructurada."
                    ),
                    "max_steps": 25,
                    "max_cost_usd": 1.5,
                    "specialty": "búsqueda web",
                },
                {
                    "name": "Investigador B",
                    "role": "researcher",
                    "model_provider": "anthropic",
                    "model_name": MEMBER_MODEL,
                    "system_prompt": (
                        "Eres un investigador. Busca en la web fuentes relevantes y "
                        "fiables, extrae datos concretos con citas y resume hallazgos "
                        "de forma estructurada."
                    ),
                    "max_steps": 25,
                    "max_cost_usd": 1.5,
                    "specialty": "búsqueda web",
                },
                {
                    "name": "Analista",
                    "role": "analyst",
                    "model_provider": "anthropic",
                    "model_name": MEMBER_MODEL,
                    "system_prompt": (
                        "Eres un analista. Sintetiza los hallazgos de los "
                        "investigadores, identifica patrones y contradicciones, y "
                        "construye tablas comparativas con conclusiones justificadas."
                    ),
                    "max_steps": 20,
                    "max_cost_usd": 1.5,
                    "specialty": "síntesis y comparación",
                },
                {
                    "name": "Redactor",
                    "role": "writer",
                    "model_provider": "anthropic",
                    "model_name": MEMBER_MODEL,
                    "system_prompt": (
                        "Eres un redactor técnico. Redacta un informe claro en Markdown "
                        "con secciones, tablas y referencias a partir del análisis "
                        "recibido."
                    ),
                    "max_steps": 15,
                    "max_cost_usd": 1.0,
                    "specialty": "redacción de informes",
                },
            ],
        },
    },
    {
        "name": "Análisis de datos",
        "description": (
            "Equipo de un solo agente DataAnalyst que escribe y ejecuta Python en "
            "sandbox para explorar datos, detectar anomalías y explicar conclusiones."
        ),
        "category": "data",
        "spec": {
            "orchestrator": {
                "name": "Coordinador de datos",
                "role": "orchestrator",
                "model_provider": "anthropic",
                "model_name": ORCHESTRATOR_MODEL,
                "system_prompt": (
                    "Eres el orquestador de un equipo de análisis de datos. Delega el "
                    "trabajo analítico al DataAnalyst y valida que las conclusiones "
                    "estén respaldadas por los datos antes de entregar."
                ),
                "max_steps": 30,
                "max_cost_usd": 2.0,
            },
            "members": [
                {
                    "name": "DataAnalyst",
                    "role": "data_analyst",
                    "model_provider": "anthropic",
                    "model_name": MEMBER_MODEL,
                    "system_prompt": (
                        "Eres un analista de datos. Escribe y ejecuta Python con "
                        "run_python para cargar los datos, calcular estadísticas, "
                        "detectar anomalías y generar gráficos. Itera sobre los errores "
                        "de ejecución y explica cada hallazgo."
                    ),
                    "max_steps": 40,
                    "max_cost_usd": 3.0,
                    "specialty": "run_python",
                },
            ],
        },
    },
    {
        "name": "Monitoreo",
        "description": (
            "Equipo de un agente evaluador de relevancia para runs programados: "
            "revisa fuentes periódicamente y solo reporta lo que supera el umbral."
        ),
        "category": "monitoring",
        "spec": {
            "orchestrator": {
                "name": "Coordinador de monitoreo",
                "role": "orchestrator",
                "model_provider": "anthropic",
                "model_name": ORCHESTRATOR_MODEL,
                "system_prompt": (
                    "Eres el orquestador de un equipo de monitoreo. Delega la revisión "
                    "de las fuentes al evaluador de relevancia y decide si hay algo que "
                    "merezca notificarse."
                ),
                "max_steps": 20,
                "max_cost_usd": 1.0,
            },
            "members": [
                {
                    "name": "Evaluador de relevancia",
                    "role": "relevance_evaluator",
                    "model_provider": "anthropic",
                    "model_name": MEMBER_MODEL,
                    "system_prompt": (
                        "Eres un evaluador de relevancia. Revisa las fuentes indicadas, "
                        "puntúa la relevancia de cada novedad frente al criterio dado y "
                        "reporta únicamente lo que supera el umbral, de forma concisa."
                    ),
                    "max_steps": 15,
                    "max_cost_usd": 0.75,
                    "specialty": "evaluación de relevancia",
                },
            ],
        },
    },
]
