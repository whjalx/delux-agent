"""Tests for edit_file tool."""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delux_agent.tools import edit_file


def _make_test_file(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


def test_edit_single_occurrence():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = _make_test_file(tmp, "test.txt", "hello world\nfoo bar\nhello again\n")

        result = edit_file("test.txt", "foo bar", "baz qux", tmp)
        assert result.ok, f"Expected ok, got: {result.output}"
        assert f.read_text() == "hello world\nbaz qux\nhello again\n"
        print("  PASS: edit_single_occurrence")


def test_edit_multiple_occurrences_rejected():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = _make_test_file(tmp, "test.txt", "hello world\nfoo bar\nhello again\n")

        result = edit_file("test.txt", "hello", "goodbye", tmp)
        assert not result.ok
        assert "appears 2 times" in result.output
        assert "lines 1, 3" in result.output
        print("  PASS: edit_multiple_occurrences_rejected")


def test_edit_replace_all():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = _make_test_file(tmp, "test.txt", "hello world\nfoo bar\nhello again\n")

        result = edit_file("test.txt", "hello", "goodbye", tmp, replace_all=True)
        assert result.ok
        assert f.read_text() == "goodbye world\nfoo bar\ngoodbye again\n"
        assert "2 occurrences" in result.output
        print("  PASS: edit_replace_all")


def test_edit_not_found():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = _make_test_file(tmp, "test.txt", "hello world\nfoo bar\n")

        result = edit_file("test.txt", "does not exist", "replacement", tmp)
        assert not result.ok
        assert "not found" in result.output
        print("  PASS: edit_not_found")


def test_edit_not_found_similar_lines():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = _make_test_file(tmp, "test.txt", "hello world\nfoo bar baz\nanother line\n")

        result = edit_file("test.txt", "foo bar qux", "replacement", tmp)
        assert not result.ok
        assert "not found" in result.output
        assert "Similar lines found" in result.output
        assert "Line 2" in result.output
        print("  PASS: edit_not_found_similar_lines")


def test_edit_identical_strings():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = _make_test_file(tmp, "test.txt", "hello world\n")

        result = edit_file("test.txt", "hello", "hello", tmp)
        assert not result.ok
        assert "identical" in result.output
        print("  PASS: edit_identical_strings")


def test_edit_file_not_exist():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        result = edit_file("nonexistent.txt", "a", "b", tmp)
        assert not result.ok
        assert "not found" in result.output
        print("  PASS: edit_file_not_exist")


def test_edit_with_whitespace():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        content = "def foo():\n    print('hello')\n    return True\n"
        f = _make_test_file(tmp, "test.py", content)

        result = edit_file("test.py", "    print('hello')", "    print('world')", tmp)
        assert result.ok
        expected = "def foo():\n    print('world')\n    return True\n"
        assert f.read_text() == expected
        print("  PASS: edit_with_whitespace")


def test_edit_multiline_block():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        content = """# Header
def old_func():
    pass

def other():
    return 1
"""
        f = _make_test_file(tmp, "test.py", content)

        result = edit_file("test.py", "def old_func():\n    pass", "def new_func():\n    return 42", tmp)
        assert result.ok
        expected = """# Header
def new_func():
    return 42

def other():
    return 1
"""
        assert f.read_text() == expected
        print("  PASS: edit_multiline_block")


def test_edit_absolute_path():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = _make_test_file(tmp, "test.txt", "original\n")
        abs_path = str(f.resolve())

        result = edit_file(abs_path, "original", "modified", tmp)
        assert result.ok
        assert f.read_text() == "modified\n"
        print("  PASS: edit_absolute_path")


def test_edit_diff_summary():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = _make_test_file(tmp, "test.txt", "line1\nline2\nline3\n")

        result = edit_file("test.txt", "line2", "new line two\nand more", tmp)
        assert result.ok
        assert "- line2" in result.output
        assert "+ new line two" in result.output
        assert "+ and more" in result.output
        print("  PASS: edit_diff_summary")


def test_edit_long_block_truncated():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        old = "\n".join(f"old line {i}" for i in range(10))
        new = "\n".join(f"new line {i}" for i in range(15))
        f = _make_test_file(tmp, "test.txt", f"before\n{old}\nafter\n")

        result = edit_file("test.txt", old, new, tmp)
        assert result.ok
        assert "7 more lines removed" in result.output
        assert "12 more lines added" in result.output
        print("  PASS: edit_long_block_truncated")


if __name__ == "__main__":
    test_edit_single_occurrence()
    test_edit_multiple_occurrences_rejected()
    test_edit_replace_all()
    test_edit_not_found()
    test_edit_not_found_similar_lines()
    test_edit_identical_strings()
    test_edit_file_not_exist()
    test_edit_with_whitespace()
    test_edit_multiline_block()
    test_edit_absolute_path()
    test_edit_diff_summary()
    test_edit_long_block_truncated()
    print(f"\n  All 12 tests passed")
