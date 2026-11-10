# -*- coding: utf-8 -*-
from __future__ import print_function

import contextlib
import glob
import os
import re
import sys
from shutil import rmtree

from invoke import Exit
from invoke import task

try:
    input = raw_input
except NameError:
    pass
BASE_FOLDER = os.path.dirname(__file__)


class Log(object):
    def __init__(self, out=sys.stdout, err=sys.stderr):
        self.out = out
        self.err = err

    def flush(self):
        self.out.flush()
        self.err.flush()

    def write(self, message):
        self.flush()
        self.out.write(message + '\n')
        self.out.flush()

    def info(self, message):
        self.write('[INFO] %s' % message)

    def warn(self, message):
        self.write('[WARN] %s' % message)


log = Log()


def confirm(question):
    while True:
        response = input(question).lower().strip()

        if not response or response in ('n', 'no'):
            return False

        if response in ('y', 'yes'):
            return True

        print('Focus, kid! It is either (y)es or (n)o', file=sys.stderr)


@task(default=True)
def help(ctx):
    """Lists available tasks and usage."""
    ctx.run('invoke --help')
    ctx.run('invoke --list')
    log.write('Use "invoke -h <taskname>" to get detailed help for a task.')


@task(help={
    'docs': 'True to generate documentation, otherwise False',
    'bytecode': 'True to clean up compiled python files, otherwise False.',
    'builds': 'True to clean up build/packaging artifacts, otherwise False.'})
def clean(ctx, docs=True, bytecode=True, builds=True):
    """Cleans the local copy from compiled artifacts."""
    if builds:
        ctx.run('python setup.py clean')

    if bytecode:
        for root, dirs, files in os.walk(BASE_FOLDER):
            for f in files:
                if f.endswith('.pyc'):
                    os.remove(os.path.join(root, f))
            if '.git' in dirs:
                dirs.remove('.git')

    folders = []

    if docs:
        folders.append('docs/_build/')
        folders.append('dist/')

    if bytecode:
        folders.append('src/roslibpy/__pycache__')

    if builds:
        folders.append('build/')
        folders.append('src/roslibpy.egg-info/')

    for folder in folders:
        rmtree(os.path.join(BASE_FOLDER, folder), ignore_errors=True)

@task(help={
      'rebuild': 'True to clean all previously built docs before starting, otherwise False.',
      'check_links': 'True to check all web links in docs for validity, otherwise False.'})
def docs(ctx, rebuild=True, check_links=False):
    """Builds package's HTML documentation."""
    if rebuild:
        clean(ctx)
    ctx.run('sphinx-build -b doctest docs dist/docs')
    ctx.run('sphinx-build -b html docs dist/docs')
    if check_links:
        ctx.run('sphinx-build -b linkcheck docs dist/docs')


@task()
def check(ctx):
    """Check the consistency of documentation, coding style and a few other things."""
    log.write('Checking MANIFEST.in...')
    ctx.run('check-manifest')

    log.write('Checking ReStructuredText formatting...')
    ctx.run('python setup.py check --strict --metadata --restructuredtext')

    log.write('Running flake8 python linter...')
    ctx.run('flake8 src tests setup.py')

    log.write('Checking python imports...')
    ctx.run('isort --check-only --diff src tests setup.py')


@task(help={
      'checks': 'True to run all checks before testing, otherwise False.'})
def test(ctx, checks=True):
    """Run all tests."""
    if checks:
        check(ctx)

    ctx.run('pytest --doctest-modules')


@task
def prepare_changelog(ctx):
    """Prepare changelog for next release."""
    UNRELEASED_CHANGELOG_TEMPLATE = '\nUnreleased\n----------\n\n**Added**\n\n**Changed**\n\n**Fixed**\n\n**Deprecated**\n\n**Removed**\n'

    with chdir(BASE_FOLDER):
        # Preparing changelog for next release
        with open('CHANGELOG.rst', 'r+') as changelog:
            content = changelog.read()
            start_index = content.index('----------')
            start_index = content.rindex('\n', 0, start_index - 1)
            last_version = content[start_index:start_index + 11].strip()

            if last_version == 'Unreleased':
                log.write('Already up-to-date')
                return

            changelog.seek(0)
            changelog.write(content[0:start_index] + UNRELEASED_CHANGELOG_TEMPLATE + content[start_index:])

        ctx.run('git add CHANGELOG.rst && git commit -m "Prepare changelog for next release"')


def changelog_to_markdown(changelog, version):
    """Convert the section of ``version`` in the CHANGELOG.rst text to GitHub Markdown.

    ``**Group**`` lines become ``## Group`` headings (empty groups are skipped),
    wrapped bullet lines are joined and ``code`` spans use single backticks.

    Raises ``ValueError`` if the section is missing, has no entries, or contains
    a line that cannot be converted, instead of silently dropping content.
    """
    lines = changelog.splitlines()

    def is_underline(line):
        return re.match(r'-{3,}$', line) is not None

    # Collect the lines of the "<version>" section (heading underlined with dashes)
    section, found, inside = [], False, False
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and is_underline(lines[i + 1]):
            if inside:
                break
            inside = line.strip() == version
            found = found or inside
            continue
        if inside and not is_underline(line):
            section.append((i + 1, line))
    if not found:
        raise ValueError('No section for {} in CHANGELOG.rst'.format(version))

    groups, current = [], None
    for lineno, line in section:
        if not line.strip():
            continue
        group = re.match(r'\*\*(.+)\*\*$', line.strip())
        if group:
            current = (group.group(1), [])
            groups.append(current)
        elif current is not None and re.match(r' *[*-] ', line):
            # Nested bullets keep their indentation, so Markdown nests them too
            current[1].append(line.rstrip())
        elif current is not None and current[1] and line.startswith(' '):
            current[1][-1] += ' ' + line.strip()
        else:
            raise ValueError('CHANGELOG.rst line {}: cannot convert {!r} to release notes; '
                             'expected a **Group** line, a bullet or an indented continuation'.format(lineno, line))

    out = []
    for title, items in groups:
        if items:
            out += ['## ' + title, ''] + [item.replace('``', '`') for item in items] + ['']
    if not out:
        raise ValueError('The {} section of CHANGELOG.rst has no entries'.format(version))
    return '\n'.join(out)


@task(help={
      'tag': 'Version (tag) to get the notes for, e.g. v2.1.0 or 2.1.0.',
      'output': 'File to also write the notes to.'})
def release_notes(ctx, tag, output=None):
    """Prints the GitHub release notes of a version, taken from CHANGELOG.rst."""
    version = tag[1:] if tag.startswith('v') else tag
    with open(os.path.join(BASE_FOLDER, 'CHANGELOG.rst'), encoding='utf-8') as changelog:
        try:
            notes = changelog_to_markdown(changelog.read(), version)
        except ValueError as e:
            raise Exit(str(e))

    if output:
        with open(output, 'w', encoding='utf-8') as f:
            f.write(notes)
    print(notes)


@task(help={
      'release_type': 'Type of release follows semver rules. Must be one of: major, minor, patch.'})
def release(ctx, release_type):
    """Releases the project in one swift command!"""
    if release_type not in ('patch', 'minor', 'major'):
        raise Exit('The release type parameter is invalid.\nMust be one of: major, minor, patch')

    # Run checks
    ctx.run('invoke check')

    # Bump version and git tag it
    ctx.run('bump2version %s --verbose' % release_type)

    # Build project
    ctx.run('python setup.py clean --all sdist bdist_wheel')

    # Prepare changelog for next release
    prepare_changelog(ctx)

    # Clean up local artifacts
    clean(ctx)

    log.write('Release preparation complete!')
    log.write('Next steps:')
    log.write('  1. Push your release branch: git push origin <branch-name>')
    log.write('  2. Push the tag: git push origin --tags')
    log.write('  3. Create a Pull Request to main')
    log.write('  4. Once merged, the release will be automatically published to PyPI')
    log.write('')
    log.write('The release workflow will verify the tag is on main before publishing.')


@contextlib.contextmanager
def chdir(dirname=None):
    current_dir = os.getcwd()
    try:
        if dirname is not None:
            os.chdir(dirname)
        yield
    finally:
        os.chdir(current_dir)
