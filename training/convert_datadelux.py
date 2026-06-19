import json
import re
import os

def remove_emojis(text):
    # Regex más agresivo para remover emojis, símbolos y selectores de variación
    return re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27BF]|[\u2000-\u3300]|[\uFE00-\uFE0F]', '', text)

def convert_datadelux(input_file, output_file):
    if not os.path.exists(input_file):
        print(f"❌ Error: {input_file} no existe.")
        return

    converted_count = 0
    with open(output_file, "w", encoding="utf-8") as out:
        with open(input_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    text = item.get("text", "")
                    
                    # Extraer user y char usando regex
                    user_match = re.search(r"{{user}}:\s*(.*?)\s*{{char}}:", text, re.DOTALL)
                    char_match = re.search(r"{{char}}:\s*(.*)", text, re.DOTALL)
                    
                    if user_match and char_match:
                        user_content = remove_emojis(user_match.group(1).strip())
                        char_content = remove_emojis(char_match.group(1).strip())
                        
                        # Formato ChatML puro sin <think>
                        formatted_item = {
                            "messages": [
                                {"role": "user", "content": user_content},
                                {"role": "assistant", "content": char_content}
                            ]
                        }
                        
                        out.write(json.dumps(formatted_item, ensure_ascii=False) + "\n")
                        converted_count += 1
                except Exception as e:
                    continue

    print(f"✅ Conversión completada: {converted_count} conversaciones procesadas.")
    print(f"📁 Archivo guardado en: {output_file}")

if __name__ == "__main__":
    convert_datadelux("/home/jcast/project/delux-agent/training/datadelux.jsonl", "/home/jcast/project/delux-agent/training/dataset_apply/chat_dataset.jsonl")
