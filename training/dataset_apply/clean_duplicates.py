import json
import os
import re

def clean_dataset(input_file, output_file):
    if not os.path.exists(input_file):
        print(f"❌ Error: {input_file} no existe.")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    original_count = len(data)
    seen_instructions = set()
    clean_data = []

    for entry in data:
        # En el motor combinatorio, la instrucción generada ya es única por diseño.
        # Solo necesitamos asegurar que no haya repeticiones literales exactas.
        instr_norm = entry["instruction"].strip()
        
        if instr_norm not in seen_instructions:
            seen_instructions.add(instr_norm)
            clean_data.append(entry)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(clean_data, f, indent=2, ensure_ascii=False)

    print(f"--- SCRIPT 1: LIMPIEZA DE DUPLICADOS ---")
    print(f"Total original: {original_count}")
    print(f"Total únicos y variados: {len(clean_data)}")
    print(f"Eliminados (redundantes): {original_count - len(clean_data)}")
    print(f"✅ Guardado en {output_file}\n")

if __name__ == "__main__":
    clean_dataset("training/dataset_apply/raw_dataset_10k.json", "training/dataset_apply/clean_dataset.json")
