import json
import random
import os

def generate_contextualizer_dataset():
    dataset = []

    # --- CATEGORÍAS TÉCNICAS ---
    web_targets = ["nginx server", "Node.js backend", "React frontend", "Apache proxy", "Django app", "Flask API", "Tomcat server", "HAProxy load balancer", "Caddy server", "Gunicorn worker"]
    web_issues = ["is returning 502", "has CORS errors", "is timing out", "shows SSL expired", "is dropping connections", "has a redirect loop", "shows 500 Internal Error"]
    web_verbs = ["Analyze logs", "Restart", "Debug", "Check config", "Reload", "Test connectivity"]

    sys_targets = ["PostgreSQL", "Docker daemon", "sshd", "Redis", "system memory", "root partition", "MongoDB", "Elasticsearch", "CPU load", "MySQL"]
    sys_issues = ["is crashing OOM", "is at 100% CPU", "has no space", "is deadlocking", "is unreachable", "has high I/O wait"]
    sys_verbs = ["Diagnose", "Monitor", "Restart", "Check status", "Kill process", "Investigate"]

    # --- NOISE TEMPLATES ---
    noise_templates = [
        "Oye Delux, {task}.", "Ayuda urgente: {task}.", "{task}. No entiendo qué pasa.", 
        "A ver si puedes con esto: {task}.", "Contexto de prod: {task}.", "Porfa haz esto: {task}", 
        "Tengo un problema gravísimo, {task}.", "Delux, {task} y avísame.", "Mira, {task}."
    ]

    def create_tech_case(target, issue, verb, domain, skills):
        task = f"{verb} {target} because it {issue}" if issue else f"{verb} {target}"
        user_input = random.choice(noise_templates).format(task=task)
        
        # USO DE <think> (ESTÁNDAR LLAMA.CPP)
        thought = random.choice([
            f"El usuario requiere {task}. Analizando la entidad {target}. El ruido conversacional es descartable. Mapeando skills a {skills[0]}.",
            f"Petición operativa detectada sobre {target}. El objetivo técnico es {task}. Generando JSON de orquestación para el agente ejecutor.",
            f"Aislando la directiva: {task}. Ignorando tono emocional. Preparando contexto de {domain}."
        ])
        
        response_json = {
            "prompt": f"Action Required: {task}.",
            "reasoning": f"Isolated technical directive for {target}.",
            "relevant_skills": skills,
            "relevant_memory": [f"Focus on {target}"]
        }
        return {"instruction": user_input, "response": f"<think>{thought}</think>\n```json\n{json.dumps(response_json, indent=2, ensure_ascii=False)}\n```"}

    # Generación Técnica (Balanceada)
    for target in web_targets:
        for issue in web_issues:
            for verb in web_verbs:
                if random.random() > 0.4:
                    dataset.append(create_tech_case(target, issue, verb, "web_server", ["networking", "web_server", "bash"]))
                    
    for target in sys_targets:
        for issue in sys_issues:
            for verb in sys_verbs:
                if random.random() > 0.4:
                    dataset.append(create_tech_case(target, issue, verb, "sysadmin", ["sysadmin", "system_tools", "bash"]))

    # --- REFUERZO DE CONVERSACIÓN (USANDO <think>) ---
    conversation_pool = [
        ("Hola", "¡Hola! Soy Delux Agent. ¿En qué sistema trabajamos hoy?"),
        ("¿Cómo estás?", "Todo en orden, listo para procesar tus comandos."),
        ("¿Quién eres?", "Soy el Contextualizer de Delux Agent, tu orquestador de sistemas."),
        ("Qué puedes hacer?", "Puedo gestionar servidores, depurar código y automatizar tareas técnicas."),
        ("Gracias", "¡De nada! Aquí sigo para lo que necesites."),
        ("Test", "Sistema operativo y listo para recibir instrucciones."),
        ("Adiós", "Hasta luego. Estaré monitoreando los servicios."),
        ("Cuéntame un chiste", "¿Por qué el programador se quedó en la ducha? Porque las instrucciones decían: Enjabona, aclara, repite.")
    ]

    for _ in range(80): # Peso extra a conversación
        for user_msg, ai_msg in conversation_pool:
            user_input = random.choice(["", "Oye ", "Hey "]) + user_msg + random.choice(["", "!", "..."])
            
            thought = f"El usuario está haciendo charla ('{user_msg}'). No hay una tarea técnica ni síntomas de error. Responderé de forma natural sin invocar herramientas."
            
            response_json = {
                "prompt": ai_msg,
                "reasoning": "Detected non-technical interaction.",
                "relevant_skills": ["interaction"],
                "relevant_memory": []
            }
            dataset.append({"instruction": user_input, "response": f"<think>{thought}</think>\n```json\n{json.dumps(response_json, indent=2, ensure_ascii=False)}\n```"})

    random.shuffle(dataset)

    output_path = "training/dataset_apply/raw_dataset_10k.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
    
    print(f"🚀 GENERACIÓN CON <think> COMPLETADA")

if __name__ == "__main__":
    generate_contextualizer_dataset()
