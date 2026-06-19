SMALL_MODEL_EXTRA_EN = """
--- SMALL MODEL HINTS ---
Keep responses short and focused. Prefer simple shell commands over complex multi-step plans.
If stuck after 2 errors, try a different approach or search_web.
For simple questions (greetings, info), respond with final directly.
"""

SMALL_MODEL_EXTRA_ES = """
--- AYUDA PARA MODELO PEQUEÑO ---
Responde breve y directo. Prefiere comandos shell simples sobre planes complejos.
Si fallas 2 veces seguidas, cambia de enfoque o busca en internet.
Para cosas simples (saludos, info), responde con final directamente.
"""


def build_small_model_prompt(lang: str = "en") -> str:
    if lang == "es":
        return SMALL_MODEL_EXTRA_ES
    return SMALL_MODEL_EXTRA_EN
