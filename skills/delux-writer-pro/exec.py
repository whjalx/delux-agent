import os
import sys

def write_pro(path, content):
    try:
        # 1. Asegurar que la ruta sea absoluta respecto al CWD
        abs_path = os.path.abspath(path)
        
        # 2. Crear directorios padres automáticamente
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        
        # 3. Escribir el archivo
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        # 4. Verificar
        if os.path.exists(abs_path):
            size = os.path.getsize(abs_path)
            return f"SUCCESS: File '{path}' written successfully ({size} bytes)."
        else:
            return f"ERROR: Failed to verify file '{path}' after writing."

    except Exception as e:
        return f"ERROR: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: delux-writer-pro <path> <content>")
        sys.exit(1)
    
    target_path = sys.argv[1]
    # Unir el resto de los argumentos como el contenido (maneja espacios)
    content_to_write = " ".join(sys.argv[2:])
    
    # Si el contenido parece venir con escapes de nueva línea literal "\n", los convertimos
    content_to_write = content_to_write.replace("\\n", "\n")
    
    print(write_pro(target_path, content_to_write))
