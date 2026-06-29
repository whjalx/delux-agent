#!/usr/bin/env python3
import os
import sys
import json
import re
import tempfile
import shutil
from datetime import datetime

VAULT_DIR = os.environ.get('OBSIDIAN_VAULT', os.path.expanduser('~/.delux/obsi'))
MAX_TOPIC_LENGTH = 200
MAX_CONTENT_LENGTH = 100_000
MAX_FILE_SIZE = 5_000_000
LOCK_RETRIES = 5


def _output(result):
    print(json.dumps(result))
    sys.exit(0)


def _error(message):
    _output({'status': 'error', 'error': str(message)})


def _ok(data):
    _output({'status': 'ok', 'data': data})


def _parse_args():
    args = sys.argv[1:]
    if not args:
        return _parse_usage()

    command = args[0].lower()
    if command not in ('add', 'read', 'list', 'search', 'delete'):
        return _parse_usage()

    if command == 'add':
        if len(args) < 3:
            _error('add requires topic and content arguments')
        topic = args[1]
        content = args[2]
        links = args[4:] if len(args) > 4 and args[3] == '-l' else []
        return command, topic, content, links

    elif command == 'read':
        if len(args) < 2:
            _error('read requires topic argument')
        return command, args[1], None, None

    elif command == 'list':
        return command, None, None, None

    elif command == 'search':
        if len(args) < 2:
            _error('search requires query argument')
        return command, args[1], None, None

    elif command == 'delete':
        if len(args) < 2:
            _error('delete requires topic argument')
        return command, args[1], None, None


def _parse_usage():
    _output({
        'status': 'error',
        'error': 'Unknown command. Available: add, read, list, search, delete',
        'data': {
            'usage': {
                'add': 'exec.py add <topic> <content> [-l <link1> <link2> ...]',
                'read': 'exec.py read <topic>',
                'list': 'exec.py list',
                'search': 'exec.py search <query>',
                'delete': 'exec.py delete <topic>',
            }
        }
    })
    sys.exit(0)


def _normalize_string(s):
    return re.sub(r'[^a-zA-Z0-9]', '', s).lower()


def _sanitize_topic(name):
    if not name or not isinstance(name, str):
        return None
    name = name.strip()
    if len(name) > MAX_TOPIC_LENGTH:
        name = name[:MAX_TOPIC_LENGTH]
    clean = ''.join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
    if not clean:
        return None
    words = clean.split()
    normalized = ' '.join(word.capitalize() for word in words)
    return normalized if normalized else None


def _init_vault():
    try:
        os.makedirs(VAULT_DIR, exist_ok=True)
    except PermissionError:
        _error(f'Permission denied creating vault directory: {VAULT_DIR}')
    except OSError as e:
        _error(f'Failed to create vault directory: {str(e)}')


def _resolve_topic(topic):
    _init_vault()
    norm = _normalize_string(topic)
    try:
        entries = os.listdir(VAULT_DIR)
    except PermissionError:
        _error(f'Permission denied reading vault: {VAULT_DIR}')
    except OSError as e:
        _error(f'Failed to list vault: {str(e)}')

    for entry in entries:
        if entry.endswith('.md'):
            base = entry[:-3]
            if _normalize_string(base) == norm:
                return base
    sanitized = _sanitize_topic(topic)
    if sanitized is None:
        _error(f'Invalid topic name: "{topic[:100]}"')
    return sanitized


def _atomic_write(filepath, content):
    fd, tmp_path = tempfile.mkstemp(dir=VAULT_DIR, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', errors='replace') as f:
            f.write(content)
        shutil.move(tmp_path, filepath)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def cmd_add(topic, content, links):
    _init_vault()

    if not topic or not isinstance(topic, str) or not topic.strip():
        _error('Topic is required and must be non-empty')
    if not content or not isinstance(content, str) or not content.strip():
        _error('Content is required and must be non-empty')

    content = content.strip()
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH]

    try:
        real_topic = _resolve_topic(topic)
    except Exception as e:
        _error(f'Failed to resolve topic: {str(e)}')

    filename = f'{real_topic}.md'
    filepath = os.path.join(VAULT_DIR, filename)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    link_str = ''
    if links:
        try:
            resolved_links = [_resolve_topic(link) for link in links]
            link_str = '\n\n**Connections:** ' + ', '.join(f'[[{link}]]' for link in resolved_links)
        except Exception:
            link_str = ''

    entry = f'\n\n## {timestamp}\n{content}{link_str}'

    try:
        if not os.path.exists(filepath):
            header = f'# {real_topic}{entry}'
            _atomic_write(filepath, header)
            _ok({
                'action': 'created',
                'topic': real_topic,
                'file': filename,
                'links': links if links else [],
            })
        else:
            try:
                file_size = os.path.getsize(filepath)
            except OSError:
                file_size = 0
            if file_size > MAX_FILE_SIZE:
                _error(f'Note file exceeds maximum size ({MAX_FILE_SIZE} bytes)')
            with open(filepath, 'a', encoding='utf-8', errors='replace') as f:
                f.write(entry)
            _ok({
                'action': 'appended',
                'topic': real_topic,
                'file': filename,
                'links': links if links else [],
            })
    except PermissionError:
        _error(f'Permission denied writing to note: {real_topic}')
    except OSError as e:
        _error(f'Failed to write note: {str(e)}')


def cmd_read(topic):
    _init_vault()

    if not topic or not isinstance(topic, str) or not topic.strip():
        _error('Topic is required')

    try:
        real_topic = _resolve_topic(topic)
    except Exception as e:
        _error(f'Failed to resolve topic: {str(e)}')

    filename = f'{real_topic}.md'
    filepath = os.path.join(VAULT_DIR, filename)

    if not os.path.exists(filepath):
        _error(f'Note not found: "{topic}" (resolved as "{real_topic}")')

    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        _error(f'Cannot access note file: {real_topic}')

    if file_size > MAX_FILE_SIZE:
        _error(f'Note file exceeds maximum readable size ({MAX_FILE_SIZE} bytes)')

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except PermissionError:
        _error(f'Permission denied reading note: {real_topic}')
    except OSError as e:
        _error(f'Failed to read note: {str(e)}')

    _ok({
        'topic': real_topic,
        'file': filename,
        'content': text,
        'size_bytes': file_size,
    })


def cmd_list():
    _init_vault()

    try:
        entries = os.listdir(VAULT_DIR)
    except PermissionError:
        _error(f'Permission denied reading vault: {VAULT_DIR}')
    except OSError as e:
        _error(f'Failed to list vault: {str(e)}')

    notes = []
    for entry in sorted(entries):
        if entry.endswith('.md'):
            filepath = os.path.join(VAULT_DIR, entry)
            try:
                size = os.path.getsize(filepath)
            except OSError:
                size = 0
            notes.append({
                'topic': entry[:-3],
                'file': entry,
                'size_bytes': size,
            })

    _ok({
        'count': len(notes),
        'notes': notes,
    })


def cmd_search(query):
    _init_vault()

    if not query or not isinstance(query, str) or not query.strip():
        _error('Search query is required')

    query_lower = query.lower()

    try:
        entries = os.listdir(VAULT_DIR)
    except PermissionError:
        _error(f'Permission denied reading vault: {VAULT_DIR}')
    except OSError as e:
        _error(f'Failed to list vault: {str(e)}')

    matches = []
    for entry in sorted(entries):
        if not entry.endswith('.md'):
            continue
        filepath = os.path.join(VAULT_DIR, entry)
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            continue
        if file_size > MAX_FILE_SIZE:
            continue
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            continue
        if query_lower in text.lower():
            lines = text.split('\n')
            matching_lines = []
            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    matching_lines.append({
                        'line_num': i + 1,
                        'text': line.strip()[:300],
                    })
                    if len(matching_lines) >= 10:
                        break
            matches.append({
                'topic': entry[:-3],
                'file': entry,
                'match_count': len(matching_lines),
                'matches': matching_lines,
            })

    _ok({
        'query': query,
        'match_count': len(matches),
        'results': matches,
    })


def cmd_delete(topic):
    _init_vault()

    if not topic or not isinstance(topic, str) or not topic.strip():
        _error('Topic is required')

    try:
        real_topic = _resolve_topic(topic)
    except Exception as e:
        _error(f'Failed to resolve topic: {str(e)}')

    filename = f'{real_topic}.md'
    filepath = os.path.join(VAULT_DIR, filename)

    if not os.path.exists(filepath):
        _error(f'Note not found: "{topic}" (resolved as "{real_topic}")')

    try:
        os.remove(filepath)
    except PermissionError:
        _error(f'Permission denied deleting note: {real_topic}')
    except OSError as e:
        _error(f'Failed to delete note: {str(e)}')

    _ok({
        'action': 'deleted',
        'topic': real_topic,
        'file': filename,
    })


def main():
    try:
        parsed = _parse_args()
        if parsed is None:
            return
        command, topic, content, links = parsed
    except Exception as e:
        _error(f'Failed to parse arguments: {str(e)}')
        return

    if command == 'add':
        cmd_add(topic, content, links)
    elif command == 'read':
        cmd_read(topic)
    elif command == 'list':
        cmd_list()
    elif command == 'search':
        cmd_search(topic)
    elif command == 'delete':
        cmd_delete(topic)
    else:
        _parse_usage()


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}))
