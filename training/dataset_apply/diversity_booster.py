import json
import os
from collections import Counter

def boost_diversity(input_file, output_file):
    if not os.path.exists(input_file):
        print(f"❌ Error: {input_file} no existe.")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"--- SCRIPT 3: DIVERSIDAD Y BARRIDO FINAL ---")
    
    # Generar casos EXTREMOS con etiqueta <think>
    extra_cases = [
        {
            "instruction": "El servidor de base de datos no arranca tras un corte de luz. Los logs dicen 'ibdata1: page 15 invalid, uncompressed page'. No hay backups recientes.",
            "response": "<think>Corrupción crítica de InnoDB. Nivel de severidad máximo. El agente necesita usar herramientas de recuperación de bajo nivel como innodb_force_recovery.</think>\n```json\n{\n  \"prompt\": \"CRITICAL DATABASE CORRUPTION DETECTED. InnoDB tablespace ibdata1 is corrupted. Initiate recovery mode. Target tool: my.cnf (set innodb_force_recovery).\",\n  \"reasoning\": \"Extracted critical severity level and identified InnoDB page corruption.\",\n  \"relevant_skills\": [\"databases\", \"mysql_recovery\"],\n  \"relevant_memory\": [\"Use innodb_force_recovery incrementally from 1 to 6.\"]\n}\n```"
        },
        {
            "instruction": "Trafico masivo saliente detectado en el puerto 53. Creemos que es un ataque de amplificación DNS.",
            "response": "<think>Posible incidente de seguridad: Exfiltración de datos vía DNS o DDoS. Se requiere captura de red inmediata.</think>\n```json\n{\n  \"prompt\": \"SECURITY INCIDENT: Massive outbound traffic on UDP/53. Target tools: tcpdump, iptables.\",\n  \"reasoning\": \"Prioritized security response.\",\n  \"relevant_skills\": [\"security\", \"networking\"],\n  \"relevant_memory\": [\"Check if local dnsmasq/bind is open resolver.\"]\n}\n```"
        }
    ]
    
    final_data = data + (extra_cases * 10)
    
    seen = set()
    unique_final = []
    for d in final_data:
        case_hash = d["instruction"].strip() + d["response"].strip()
        if case_hash not in seen:
            seen.add(case_hash)
            unique_final.append(d)

    with open(output_file, "w", encoding="utf-8") as f:
        for item in unique_final:
            chat_format = {
                "messages": [
                    {"role": "user", "content": item["instruction"]},
                    {"role": "assistant", "content": item["response"]}
                ]
            }
            f.write(json.dumps(chat_format, ensure_ascii=False) + "\n")

    print(f"RESULTADO FINAL (GOLDEN DATASET): {len(unique_final)} casos limpios con <think>.")

if __name__ == "__main__":
    boost_diversity("training/dataset_apply/sorted_dataset.json", "training/dataset_apply/golden_dataset.jsonl")
