#!/usr/bin/env python3
import os
import sys
from collections import Counter

EXT_MAP = {
    '.py': 'Python',
    '.js': 'JavaScript',
    '.ts': 'TypeScript',
    '.tsx': 'React TS',
    '.jsx': 'React JS',
    '.html': 'HTML',
    '.css': 'CSS',
    '.md': 'Markdown',
    '.sh': 'Shell',
    '.bash': 'Shell',
    '.fish': 'Shell',
    '.c': 'C',
    '.cpp': 'C++',
    '.h': 'Header',
    '.go': 'Go',
    '.rs': 'Rust',
    '.json': 'JSON',
    '.yml': 'YAML',
    '.yaml': 'YAML',
    '.toml': 'TOML',
}

def main():
    print("\033[1;35m=== Codebase Statistics ===\033[0m")
    
    stats = Counter()
    lines = Counter()
    total_files = 0
    total_lines = 0
    
    ignore_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build'}
    
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            lang = EXT_MAP.get(ext)
            if lang:
                total_files += 1
                stats[lang] += 1
                try:
                    with open(os.path.join(root, file), 'r', encoding='utf-8', errors='ignore') as f:
                        count = sum(1 for _ in f)
                        lines[lang] += count
                        total_lines += count
                except:
                    pass

    if total_files == 0:
        print("No supported code files found in the current directory.")
        return

    print(f"\033[1mTotal Files:\033[0m {total_files}")
    print(f"\033[1mTotal Lines:\033[0m {total_lines}")
    print("\n\033[1mLanguage Distribution:\033[0m")
    
    # Sort by lines
    sorted_langs = sorted(lines.items(), key=lambda x: x[1], reverse=True)
    
    for lang, line_count in sorted_langs:
        file_count = stats[lang]
        pct = (line_count / total_lines) * 100 if total_lines > 0 else 0
        print(f"  {lang:12} : {line_count:6} lines ({pct:5.1f}%) in {file_count:4} files")

if __name__ == "__main__":
    main()
