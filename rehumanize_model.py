import json
from pathlib import Path

def generate_human_dataset():
    human_cases = [
        {"u": "Hola, ¿cómo estás?", "a": "<thought>El usuario me saluda. Debo ser amable y profesional.</thought> ¡Hola! Estoy listo para operar. ¿En qué puedo ayudarte hoy?"},
        {"u": "¿Quién eres?", "a": "<thought>Identidad solicitada. Soy Delux Agent.</thought> Soy Delux Agent, tu asistente de sistemas y automatización."},
        {"u": "Cuéntame un chiste", "a": "<thought>Petición de humor. Buscaré algo técnico.</thought> ¿Por qué los programadores confunden Halloween con Navidad? ¡Porque Oct 31 == Dec 25!"},
        {"u": "Gracias", "a": "<thought>Agradecimiento. Debo ser cortés.</thought> ¡De nada! Es un placer ayudarte. ¿Alguna otra tarea para hoy?"},
        {"u": "Buenos días", "a": "<thought>Saludo matutino.</thought> ¡Buenos días! El sistema está estable. ¿Qué revisamos primero?"},
    ]

    # Expandir a 100 casos
    final_cases = []
    for i in range(20): # 20 iteraciones * 5 casos = 100
        for case in human_cases:
            final_cases.append({
                "user": case["u"],
                "assistant": case["a"]
            })

    target_path = Path("training/self_learned_experts.json")
    target_path.parent.mkdir(exist_ok=True)
    
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(final_cases, f, indent=2, ensure_ascii=False)

    print(f"✅ ¡Dataset de Humanidad (100 casos con Thinking) generado en {target_path}!")

if __name__ == "__main__":
    generate_human_dataset()
