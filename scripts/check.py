"""Run existing repository checks without enabling paid-provider tests."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def changed_files(base: str) -> list[str]:
    def git(*args: str) -> list[str]:
        result = subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True)
        return [os.fsdecode(value) for value in result.stdout.split(b'\0') if value]
    subprocess.run(['git', 'rev-parse', '--verify', base + '^{commit}'], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return sorted(set(git('diff', '--name-only', '--diff-filter=ACMR', '-z', base) + git('ls-files', '--others', '--exclude-standard', '-z')))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-only', action='store_true', help='Used by the existing pre-commit pytest hook.')
    parser.add_argument('--base', default='HEAD', help='Lint changes since this commit; include local changes.')
    parser.add_argument('--all-files', action='store_true', help='Explicit full-tree lint audit, including legacy files.')
    parser.add_argument('--install-hooks', action='store_true')
    args = parser.parse_args(argv)
    if args.unit_only:
        # Keep pytest.ini defaults. Explicitly retain the offline marker boundary.
        suites = [name for name in ('tests/unit', 'tests/test_mineru')
                  if (ROOT / name).is_dir()]
        command = [sys.executable, '-m', 'pytest', *suites, '-q', '-m', 'not integration and not e2e']
    elif args.install_hooks:
        subprocess.run(['git', 'config', '--local', 'agent.python', sys.executable], cwd=ROOT, check=True)
        command = [sys.executable, '-m', 'pre_commit', 'install']
    else:
        command = [sys.executable, '-m', 'pre_commit', 'run']
        if args.all_files:
            command += ['--all-files']
        else:
            files = changed_files(args.base)
            if files:
                command += ['--files', *files]
    environment = {**os.environ, 'PYTHON_DOTENV_DISABLED': '1',
                   'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')}
    return subprocess.run(command, cwd=ROOT, env=environment).returncode


if __name__ == '__main__':
    # Git hooks use the interpreter selected at installation, not an unrelated PATH Python.
    configured = subprocess.run(['git', 'config', '--get', 'agent.python'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if configured and Path(configured).resolve() != Path(sys.executable).resolve():
        if not Path(configured).is_file():
            raise SystemExit('Configured project Python is missing; reinstall hooks from the development environment.')
        raise SystemExit(subprocess.run([configured, str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT).returncode)
    raise SystemExit(main())
