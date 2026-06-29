#!/usr/bin/env python3
import os
import sys
import json
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

IGNORE_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build', '.tox', '.mypy_cache', '.pytest_cache', 'target'}
BINARY_MAGIC_BYTES = (0, 127)  # NUL and DEL as common binary indicators
MAX_FILE_SIZE = 5_000_000  # 5MB skip threshold for performance
TEXT_SCAN_MAX = 4096


def _is_text_file(filepath):
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(TEXT_SCAN_MAX)
            for byte in chunk:
                if byte == 0:
                    return False
            return True
    except Exception:
        return False


def _count_file_lines(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _walk_directory(root_path, ignore_dirs):
    stats = Counter()
    lines = Counter()
    total_files = 0
    total_lines = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith('.')]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            lang = EXT_MAP.get(ext)
            if lang is None:
                continue
            filepath = os.path.join(dirpath, filename)
            try:
                file_stat = os.stat(filepath)
            except OSError:
                continue
            if file_stat.st_size > MAX_FILE_SIZE:
                continue
            if not _is_text_file(filepath):
                continue
            total_files += 1
            stats[lang] += 1
            count = _count_file_lines(filepath)
            lines[lang] += count
            total_lines += count

    return stats, lines, total_files, total_lines


def _build_result(root_path, stats, lines, total_files, total_lines):
    breakdown = []
    sorted_langs = sorted(lines.keys(), key=lambda k: lines[k], reverse=True)
    for lang in sorted_langs:
        line_count = lines[lang]
        file_count = stats[lang]
        pct = round((line_count / total_lines) * 100, 1) if total_lines > 0 else 0.0
        breakdown.append({
            'language': lang,
            'lines': line_count,
            'files': file_count,
            'percentage': pct,
        })

    return {
        'target': root_path,
        'total_files': total_files,
        'total_lines': total_lines,
        'languages': breakdown,
    }


def main():
    try:
        if len(sys.argv) > 2:
            print(json.dumps({'status': 'error', 'error': 'Usage: exec.py [path]'}))
            sys.exit(0)

        target = sys.argv[1] if len(sys.argv) == 2 else os.getcwd()

        if not isinstance(target, str) or not target.strip():
            print(json.dumps({'status': 'error', 'error': 'Invalid path argument'}))
            sys.exit(0)

        target = os.path.abspath(target)

        if not os.path.exists(target):
            print(json.dumps({'status': 'error', 'error': f'Path not found: {target}'}))
            sys.exit(0)

        if not os.path.isdir(target):
            print(json.dumps({'status': 'error', 'error': f'Not a directory: {target}'}))
            sys.exit(0)

        stats, lines, total_files, total_lines = _walk_directory(target, IGNORE_DIRS)

        data = _build_result(target, stats, lines, total_files, total_lines)
        print(json.dumps({'status': 'ok', 'data': data}))

    except PermissionError:
        print(json.dumps({'status': 'error', 'error': 'Permission denied accessing path'}))
    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}))


if __name__ == '__main__':
    main()
