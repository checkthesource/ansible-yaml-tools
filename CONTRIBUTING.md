# Contributing

Thanks for helping! Bug reports, ideas and pull requests are all welcome.

## Reporting a bug

Open an issue with:

- the task you ran (with its options),
- a minimal YAML file that shows the problem (remove anything secret),
- what you expected and what happened,
- the versions of ansible-core, Python and ruamel.yaml on the managed node.

Security problems must be reported privately, see [SECURITY.md](SECURITY.md).

## Setting up

`ansible-test` needs the repository to live in an `ansible_collections`
tree:

```bash
mkdir -p ~/src/ansible_collections/checkthesource
git clone https://github.com/checkthesource/ansible-yaml-tools.git \
    ~/src/ansible_collections/checkthesource/yaml_tools
cd ~/src/ansible_collections/checkthesource/yaml_tools
python -m venv .venv && . .venv/bin/activate
pip install ansible-core ansible-lint antsibull-changelog ruamel.yaml pytest
```

## Layout

| Path | Content |
| --- | --- |
| `plugins/module_utils/yaml_core.py` | The editing engine, shared by every module. It works on strings and never touches the filesystem, except for the file helpers at the end. |
| `plugins/modules/` | The modules. They only declare options, call the engine and report results. |
| `plugins/doc_fragments/common.py` | Documentation of the options shared by every module. |
| `tests/unit/` | Unit tests of the engine (pytest). |
| `tests/integration/targets/` | Integration tests, one target per module. |
| `changelogs/` | Changelog data, managed by antsibull-changelog. |

## Design rules

- **Never write unverified data.** Every edit goes through `run_plan()`, which
  compares the new document with the expected data before anything is
  written.
- **Lossless first.** A new feature should change only the text it targets.
  If that's impossible in some case, raise `LosslessUnsupported` so that the
  round-trip fallback (or a clear error in `edit_mode: lossless`) takes over.
- **Idempotent.** Running the same task twice must report `changed: false`
  the second time.
- **No secrets in errors.** Error messages must not include file content.

## Before opening a pull request

Run the tests:

```bash
python -m pytest tests/unit
ansible-test sanity --docker
ansible-test integration --docker
ansible-lint --profile production
```

Add tests for the change: unit tests for the engine, and an integration test
when the module options or results change.

Add a changelog fragment, unless the change is invisible to users (tests,
CI, typos). Create a YAML file in `changelogs/fragments/`, named after the
change:

```yaml
# changelogs/fragments/123-yaml-list-items.yml
minor_changes:
  - yaml_list - add the ``items`` option to add several items at once (https://github.com/checkthesource/ansible-yaml-tools/pull/123).
```

The sections are `major_changes`, `minor_changes`, `breaking_changes`,
`deprecated_features`, `removed_features`, `security_fixes`, `bugfixes` and
`known_issues`. Check fragments with `antsibull-changelog lint`.

New options and modules need `version_added` set to the next release.
