#!/usr/bin/env python3
import sys
import json
import os
import re
from pathlib import Path

EXT_MAP = {
    '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
    '.tsx': 'TypeScript React', '.jsx': 'JavaScript React',
    '.go': 'Go', '.rs': 'Rust', '.c': 'C', '.cpp': 'C++',
    '.h': 'C/C++ Header', '.java': 'Java', '.rb': 'Ruby',
    '.sh': 'Bash', '.bash': 'Bash', '.zsh': 'Zsh',
    '.yaml': 'YAML', '.yml': 'YAML', '.json': 'JSON',
    '.toml': 'TOML', '.ini': 'INI', '.cfg': 'Config',
    '.md': 'Markdown', '.rst': 'reStructuredText',
    '.html': 'HTML', '.css': 'CSS', '.scss': 'SCSS',
    '.sql': 'SQL', '.php': 'PHP', '.swift': 'Swift',
    '.kt': 'Kotlin', '.kts': 'Kotlin Script',
    '.dockerfile': 'Dockerfile', '.Dockerfile': 'Dockerfile',
}

SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
             'target', 'build', 'dist', '.tox', '.mypy_cache', '.pytest_cache'}
MAX_FILE_SIZE = 1_048_576  # 1MB
MAX_FILES = 5000
TEXT_SCAN_MAX = 4096

FUNC_PATTERNS = {
    'Python': re.compile(r'^\s*def\s+\w+', re.MULTILINE),
    'JavaScript': re.compile(r'^\s*(function\s+\w+|const\s+\w+\s*=\s*(?:async\s+)?\(|let\s+\w+\s*=\s*(?:async\s+)?\(|var\s+\w+\s*=\s*(?:async\s+)?\()', re.MULTILINE),
    'TypeScript': re.compile(r'^\s*(function\s+\w+|const\s+\w+\s*=\s*(?:async\s+)?\(|let\s+\w+\s*=\s*(?:async\s+)?\()', re.MULTILINE),
    'TypeScript React': re.compile(r'^\s*(function\s+\w+|const\s+\w+\s*=\s*(?:async\s+)?\(|let\s+\w+\s*=\s*(?:async\s+)?\()', re.MULTILINE),
    'JavaScript React': re.compile(r'^\s*(function\s+\w+|const\s+\w+\s*=\s*(?:async\s+)?\(|let\s+\w+\s*=\s*(?:async\s+)?\()', re.MULTILINE),
    'Go': re.compile(r'^\s*func\s+\w+', re.MULTILINE),
    'Rust': re.compile(r'^\s*(pub\s+)?fn\s+\w+', re.MULTILINE),
    'C': re.compile(r'^\s*\w[\w\s*]+\s+\w+\s*\(', re.MULTILINE),
    'C++': re.compile(r'^\s*\w[\w\s*:]+\s+\w+::\w+\s*\(|^\s*\w[\w\s*]+\s+\w+\s*\(', re.MULTILINE),
    'C/C++ Header': re.compile(r'^\s*\w[\w\s*]+\s+\w+\s*\(', re.MULTILINE),
    'Java': re.compile(r'^\s*(public|private|protected|static|\s)*\w[\w\s<>]*\s+\w+\s*\(', re.MULTILINE),
    'Ruby': re.compile(r'^\s*def\s+\w+', re.MULTILINE),
    'PHP': re.compile(r'^\s*(public\s+)?function\s+\w+', re.MULTILINE),
    'Swift': re.compile(r'^\s*func\s+\w+', re.MULTILINE),
    'Kotlin': re.compile(r'^\s*(fun\s+\w+|val\s+\w+\s*=\s*\{)', re.MULTILINE),
    'Kotlin Script': re.compile(r'^\s*(fun\s+\w+|val\s+\w+\s*=\s*\{)', re.MULTILINE),
}

CLASS_PATTERNS = {
    'Python': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'JavaScript': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'TypeScript': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'TypeScript React': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'JavaScript React': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'Go': re.compile(r'^\s*type\s+\w+\s+struct', re.MULTILINE),
    'Rust': re.compile(r'^\s*(pub\s+)?(struct|enum|trait|impl)\s+\w+', re.MULTILINE),
    'C++': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'C/C++ Header': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'Java': re.compile(r'^\s*(public\s+)?class\s+\w+', re.MULTILINE),
    'Ruby': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'Kotlin': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'Kotlin Script': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'Swift': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
    'PHP': re.compile(r'^\s*class\s+\w+', re.MULTILINE),
}

COMMENT_PATTERNS = {
    'Python': re.compile(r'^\s*#'),
    'Shell': re.compile(r'^\s*#'),
    'Bash': re.compile(r'^\s*#'),
    'Zsh': re.compile(r'^\s*#'),
    'Ruby': re.compile(r'^\s*#'),
    'YAML': re.compile(r'^\s*#'),
    'TOML': re.compile(r'^\s*#'),
    'INI': re.compile(r'^\s*[#;]'),
    'Config': re.compile(r'^\s*[#;]'),
}

JS_COMMENT_PATTERNS = re.compile(r'^\s*//|/\*|\*')

HTML_COMMENT_PATTERN = re.compile(r'<!--')


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


def _detect_language(path):
    suffix = Path(path).suffix.lower()
    if not suffix:
        name = os.path.basename(path).lower()
        if name == 'dockerfile':
            return 'Dockerfile'
        if name == 'makefile':
            return 'Makefile'
        return 'Unknown'
    return EXT_MAP.get(suffix, suffix.lstrip('.') or 'Unknown')


def _count_comments(content, language):
    if language in COMMENT_PATTERNS:
        return len(COMMENT_PATTERNS[language].findall(content))
    if language in ('JavaScript', 'TypeScript', 'JavaScript React', 'TypeScript React', 'Go', 'Rust', 'C', 'C++', 'C/C++ Header', 'Java', 'Kotlin', 'Kotlin Script', 'Swift', 'PHP'):
        return len(re.findall(r'^\s*//|^\s*\*|/\*|\*/', content, re.MULTILINE))
    if language == 'HTML':
        return len(HTML_COMMENT_PATTERN.findall(content))
    return 0


def _analyze_file(filepath):
    path_str = str(filepath)
    lang = _detect_language(path_str)
    result = {
        'path': path_str,
        'language': lang,
        'lines': 0,
        'functions': 0,
        'classes': 0,
        'comments': 0,
        'size_bytes': 0,
    }
    try:
        if filepath.is_symlink():
            result['error'] = 'Symlinks are not followed'
            st = os.lstat(path_str)
            result['size_bytes'] = st.st_size
            return result
        st = os.stat(path_str)
        result['size_bytes'] = st.st_size
        if st.st_size > MAX_FILE_SIZE:
            result['error'] = f'File exceeds {MAX_FILE_SIZE} bytes limit'
            return result
        if not _is_text_file(path_str):
            result['error'] = 'Binary file skipped'
            return result

        with open(path_str, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        lines = content.split('\n')
        result['lines'] = len(lines)
        if lang in FUNC_PATTERNS:
            result['functions'] = len(FUNC_PATTERNS[lang].findall(content))
        if lang in CLASS_PATTERNS:
            result['classes'] = len(CLASS_PATTERNS[lang].findall(content))
        result['comments'] = _count_comments(content, lang)
    except PermissionError:
        result['error'] = 'Permission denied'
    except OSError as e:
        result['error'] = str(e)
    except Exception as e:
        result['error'] = str(e)
    return result


def _analyze_directory(target):
    files = []
    total_size = 0
    lang_counts = {}
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for filename in filenames:
            if file_count >= MAX_FILES:
                break
            fpath = Path(os.path.join(dirpath, filename))
            try:
                if fpath.is_symlink():
                    continue
                st = os.stat(str(fpath))
            except OSError:
                continue
            if st.st_size > MAX_FILE_SIZE:
                continue
            lang = _detect_language(str(fpath))
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            total_size += st.st_size
            files.append({'path': str(fpath), 'language': lang, 'size': st.st_size})
            file_count += 1
        if file_count >= MAX_FILES:
            break

    files.sort(key=lambda x: x['size'], reverse=True)
    top_files = files[:20]

    return {
        'total_files': len(files),
        'total_size_bytes': total_size,
        'language_distribution': lang_counts,
        'top_files_by_size': top_files,
    }


def main():
    try:
        if len(sys.argv) > 2:
            print(json.dumps({'status': 'error', 'error': 'Usage: exec.py [path]'}))
            sys.exit(0)

        path_arg = sys.argv[1] if len(sys.argv) == 2 else os.getcwd()
        if not isinstance(path_arg, str) or not path_arg.strip():
            print(json.dumps({'status': 'error', 'error': 'Invalid path argument'}))
            sys.exit(0)

        target = Path(path_arg).resolve()

    except Exception as e:
        print(json.dumps({'status': 'error', 'error': f'Invalid path: {str(e)}'}))
        sys.exit(0)

    try:
        if not target.exists():
            print(json.dumps({'status': 'error', 'error': f'Path not found: {target}'}))
            sys.exit(0)

        if target.is_file():
            analysis = _analyze_file(target)
            data = {
                'mode': 'analyze',
                'target': str(target),
                'type': 'file',
                'analysis': analysis,
            }
        elif target.is_dir():
            dir_data = _analyze_directory(target)
            data = {
                'mode': 'analyze',
                'target': str(target),
                'type': 'directory',
                **dir_data,
            }
        else:
            print(json.dumps({'status': 'error', 'error': f'Unsupported path type: {target}'}))
            sys.exit(0)

        print(json.dumps({'status': 'ok', 'data': data}))

    except PermissionError:
        print(json.dumps({'status': 'error', 'error': f'Permission denied: {target}'}))
    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}))


if __name__ == '__main__':
    main()
