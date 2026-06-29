#!/usr/bin/env python3
import sys
import json
import os
import glob as globmod

DELUX_HOME = os.path.expanduser('~/.delux')
SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '')

TEXT_EXTENSIONS = {
    '.md', '.txt', '.py', '.js', '.ts', '.json', '.yaml', '.yml', '.toml',
    '.sh', '.bash', '.cfg', '.ini', '.conf', '.env', '.html', '.css', '.sql',
    '.go', '.rs', '.c', '.h', '.cpp', '.java', '.rb', '.php', '.swift', '.kt',
}

SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
             'target', 'build', 'dist', '.tox', '.mypy_cache', '.pytest_cache',
             'dataset-rag', 'rag'}

MAX_FILE_SIZE = 500_000
MAX_FILES_PER_SOURCE = 200
MAX_MATCHES = 10
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


def _search_path(search_path, query, label):
    results = []
    if not os.path.isdir(search_path):
        return results

    query_lower = query.lower()
    files_scanned = 0

    try:
        walker = os.walk(search_path)
    except PermissionError:
        return results

    for root, dirs, files in walker:
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for fname in files:
            if files_scanned >= MAX_FILES_PER_SOURCE or len(results) >= MAX_MATCHES:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext and ext not in TEXT_EXTENSIONS:
                name_lower = fname.lower()
                if name_lower not in {'dockerfile', 'makefile', 'readme', 'license',
                                       'changelog', 'todo', 'requirements', 'package',
                                       'compose', 'justfile'}:
                    continue
            fpath = os.path.join(root, fname)
            try:
                st = os.stat(fpath)
                if st.st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            if not _is_text_file(fpath):
                continue
            files_scanned += 1
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read(100_000)
            except OSError:
                continue
            if query_lower in content.lower():
                lines = content.split('\n')
                matching_lines = []
                for i, line in enumerate(lines):
                    if query_lower in line.lower():
                        matching_lines.append({
                            'line_num': i + 1,
                            'text': line.strip()[:200],
                        })
                        if len(matching_lines) >= 5:
                            break
                results.append({
                    'source': f'{label}/{os.path.relpath(fpath, search_path)}',
                    'file_path': fpath,
                    'matches': matching_lines,
                    'match_count': len(matching_lines),
                })
                if len(results) >= MAX_MATCHES:
                    break
        if files_scanned >= MAX_FILES_PER_SOURCE or len(results) >= MAX_MATCHES:
            break

    return results


def _search_skills(query):
    results = []
    query_lower = query.lower()
    try:
        skill_files = globmod.glob(os.path.join(SKILLS_DIR, '*', 'SKILL.md'))
    except Exception:
        return results

    for sf in skill_files:
        if len(results) >= MAX_MATCHES:
            break
        try:
            with open(sf, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except OSError:
            continue
        if query_lower in content.lower():
            results.append({
                'source': f'skills/{os.path.basename(os.path.dirname(sf))}',
                'file_path': sf,
                'matches': [{'line_num': 0, 'text': 'Relevant skill found'}],
                'match_count': 1,
            })
    return results


def main():
    try:
        query = ' '.join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ''
        if not query:
            _output({'status': 'error', 'error': 'No query provided. Usage: exec.py <query>'})
            return

        sources_checked = []
        findings = []

        if os.path.isdir(DELUX_HOME):
            sources_checked.append('memory')
            try:
                mem_results = _search_path(DELUX_HOME, query, 'memory')
                findings.extend(mem_results)
            except Exception:
                pass

        docs_dir = os.path.join(DELUX_HOME, 'docs')
        if os.path.isdir(docs_dir):
            sources_checked.append('docs')
            try:
                doc_results = _search_path(docs_dir, query, 'docs')
                findings.extend(doc_results[:MAX_MATCHES - len(findings)])
            except Exception:
                pass

        if len(findings) < MAX_MATCHES:
            sources_checked.append('skills')
            try:
                skill_results = _search_skills(query)
                findings.extend(skill_results[:MAX_MATCHES - len(findings)])
            except Exception:
                pass

        confidence = round(min(0.95, 0.5 + (len(findings) * 0.1)), 2)

        status = 'complete' if findings else 'no_results'

        _output({
            'status': 'ok',
            'data': {
                'query': query,
                'sources_checked': sources_checked,
                'status': status,
                'confidence': confidence,
                'findings': findings,
            },
        })

    except Exception as e:
        _output({'status': 'error', 'error': str(e)})


def _output(result):
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}))
