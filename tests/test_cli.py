"""Tests for the CLI."""

import io
import json
import tempfile
from pathlib import Path

import pytest

from flake8_stepdown.cli import main

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestCheckCommand:
    """Tests for the check subcommand."""

    def test_clean_exit_0(self) -> None:
        """No violations returns exit code 0."""
        fixture = str(FIXTURES_DIR / "already_correct.py")
        assert main(["check", fixture]) == 0

    def test_violations_exit_1(self) -> None:
        """Violations found returns exit code 1."""
        fixture = str(FIXTURES_DIR / "simple_bottomup.py")
        assert main(["check", fixture]) == 1

    def test_error_exit_2(self) -> None:
        """Invalid file returns exit code 2."""
        assert main(["check", "nonexistent_file.py"]) == 2

    def test_json_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        """JSON format produces valid JSON output."""
        fixture = str(FIXTURES_DIR / "simple_bottomup.py")
        main(["check", "--format", "json", fixture])
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)

    def test_verbose_shows_mutual_recursion(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verbose flag shows mutual recursion info on stderr."""
        fixture = str(FIXTURES_DIR / "mutual_recursion.py")
        main(["check", "-v", fixture])
        captured = capsys.readouterr()
        assert "mutual recursion" in captured.err

    def test_stdin_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Check with --stdin-filename reads from stdin."""
        source = """\
def b():
    pass


def a():
    b()
"""
        monkeypatch.setattr("sys.stdin", io.StringIO(source))
        exit_code = main(["check", "--stdin-filename", "test.py"])
        assert exit_code == 1

    def test_empty_file(self) -> None:
        """Check on an empty file returns exit code 0."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
        ) as f:
            f.write("")
            tmp_path = Path(f.name)

        try:
            assert main(["check", str(tmp_path)]) == 0
        finally:
            tmp_path.unlink()

    def test_binary_file_error(self) -> None:
        """Binary file returns exit code 2."""
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".py",
            delete=False,
        ) as f:
            f.write(b"\x80\x81\x82\xff\xfe")
            tmp_path = Path(f.name)

        try:
            exit_code = main(["check", str(tmp_path)])
            assert exit_code == 2
        finally:
            tmp_path.unlink()

    def test_multiple_files(self) -> None:
        """Process multiple files."""
        f1 = str(FIXTURES_DIR / "already_correct.py")
        f2 = str(FIXTURES_DIR / "simple_bottomup.py")
        exit_code = main(["check", f1, f2])
        assert exit_code == 1  # at least one has violations


class TestDiffCommand:
    """Tests for the diff subcommand."""

    def test_shows_diff(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Diff command shows unified diff."""
        fixture = str(FIXTURES_DIR / "simple_bottomup.py")
        exit_code = main(["diff", fixture])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "---" in captured.out

    def test_no_diff_exit_0(self) -> None:
        """No diff needed returns exit code 0."""
        fixture = str(FIXTURES_DIR / "already_correct.py")
        assert main(["diff", fixture]) == 0


class TestFixCommand:
    """Tests for the fix subcommand."""

    def test_rewrites_file(self) -> None:
        """Fix command rewrites file in place."""
        source = """\
def b():
    pass


def a():
    b()
"""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
        ) as f:
            f.write(source)
            tmp_path = Path(f.name)

        try:
            exit_code = main(["fix", str(tmp_path)])
            assert exit_code == 1
            result = tmp_path.read_text()
            assert result.index("def a") < result.index("def b")
        finally:
            tmp_path.unlink()

    def test_no_change_exit_0(self) -> None:
        """Already correct file returns exit code 0."""
        fixture = FIXTURES_DIR / "already_correct.py"
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
        ) as f:
            f.write(fixture.read_text())
            tmp_path = Path(f.name)

        try:
            assert main(["fix", str(tmp_path)]) == 0
        finally:
            tmp_path.unlink()

    def test_verbose_no_change(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Fix with --verbose on already correct file shows no mutual recursion."""
        fixture = FIXTURES_DIR / "already_correct.py"
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
        ) as f:
            f.write(fixture.read_text())
            tmp_path = Path(f.name)

        try:
            exit_code = main(["fix", "-v", str(tmp_path)])
            assert exit_code == 0
            captured = capsys.readouterr()
            assert "mutual recursion" not in captured.err
        finally:
            tmp_path.unlink()
