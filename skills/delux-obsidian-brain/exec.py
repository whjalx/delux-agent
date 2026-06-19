#!/usr/bin/env python3
import os
import sys
import argparse
from datetime import datetime

# Definir la ruta del vault de Obsidian. Por defecto, en la carpeta ~/.delux/obsi
VAULT_DIR = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/.delux/obsi"))

import re

def init_vault():
    if not os.path.exists(VAULT_DIR):
        os.makedirs(VAULT_DIR)
        print(f"Inicializado el cerebro (vault) de Obsidian en: {VAULT_DIR}")

def normalize_string(s):
    return re.sub(r'[^a-zA-Z0-9]', '', s).lower()

def sanitize_name(name):
    clean = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
    return " ".join(word.capitalize() if word.islower() else word for word in clean.split())

def resolve_topic_name(name):
    init_vault()
    norm_name = normalize_string(name)
    existing_files = [f for f in os.listdir(VAULT_DIR) if f.endswith('.md')]
    
    for f in existing_files:
        base_name = f[:-3]
        if normalize_string(base_name) == norm_name:
            return base_name
            
    return sanitize_name(name)

def add_note(topic, content, links=None):
    init_vault()
    
    real_topic = resolve_topic_name(topic)
    filename = f"{real_topic}.md"
    filepath = os.path.join(VAULT_DIR, filename)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    link_str = ""
    if links:
        resolved_links = [resolve_topic_name(link) for link in links]
        link_str = "\n\n**Conexiones:** " + ", ".join([f"[[{link}]]" for link in resolved_links])
        
    entry = f"\n\n## {timestamp}\n{content}{link_str}"
    
    if not os.path.exists(filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {real_topic}")
            f.write(entry)
        print(f"✅ Creada nueva nota: [[{real_topic}]]")
    else:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry)
        print(f"✅ Agregado contenido a la nota: [[{real_topic}]]")

def read_note(topic):
    init_vault()
    real_topic = resolve_topic_name(topic)
    filename = f"{real_topic}.md"
    filepath = os.path.join(VAULT_DIR, filename)
    
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            print(f.read())
    else:
        print(f"❌ La nota '{topic}' (resuelta como '{real_topic}') no existe en el cerebro.")

def list_notes():
    init_vault()
    notes = [f for f in os.listdir(VAULT_DIR) if f.endswith('.md')]
    if not notes:
        print("El cerebro está vacío. No hay notas aún.")
    else:
        print("🧠 Notas en el cerebro (Obsidian):")
        for n in notes:
            print(f"- [[{n[:-3]}]]")

def main():
    parser = argparse.ArgumentParser(description="Skill Obsidian Learning Brain - Base de Conocimiento y Aprendizaje Profundo del Agente. Guarda investigaciones, documentacion y ejemplos.")
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")
    
    # Add
    parser_add = subparsers.add_parser("add", help="Agregar o crear una nota nueva")
    parser_add.add_argument("topic", type=str, help="Tema o título de la nota")
    parser_add.add_argument("content", type=str, help="Contenido o información a memorizar")
    parser_add.add_argument("-l", "--links", type=str, nargs="+", help="Temas relacionados para conectar usando grafos (crea la sintaxis [[Link]])")
    
    # Read
    parser_read = subparsers.add_parser("read", help="Leer una nota existente")
    parser_read.add_argument("topic", type=str, help="Tema o título de la nota a leer")
    
    # List
    subparsers.add_parser("list", help="Listar todas las notas en el cerebro")

    args = parser.parse_args()

    if args.command == "add":
        add_note(args.topic, args.content, args.links)
    elif args.command == "read":
        read_note(args.topic)
    elif args.command == "list":
        list_notes()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
