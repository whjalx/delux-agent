import json
import os

def sort_dataset(input_file, output_file):
    if not os.path.exists(input_file):
        print(f"❌ Error: {input_file} no existe.")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Ordenar por longitud de la respuesta (más largo primero)
    sorted_data = sorted(data, key=lambda x: len(x["response"]), reverse=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(sorted_data, f, indent=2, ensure_ascii=False)

    print(f"--- SCRIPT 2: ORDENAMIENTO POR COMPLEJIDAD ---")
    print(f"Total procesados: {len(sorted_data)}")
    print(f"Ejemplo más largo: {len(sorted_data[0]['response'])} caracteres")
    print(f"Ejemplo más corto: {len(sorted_data[-1]['response'])} caracteres")
    print(f"✅ Guardado en {output_file}\n")

if __name__ == "__main__":
    sort_dataset("training/dataset_apply/clean_dataset.json", "training/dataset_apply/sorted_dataset.json")
