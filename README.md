# checkthesource.yaml_tools — edit YAML files from Ansible without reformatting them

[![CI](https://github.com/checkthesource/ansible-yaml-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/checkthesource/ansible-yaml-tools/actions/workflows/ci.yml)
[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)

An Ansible collection to change values and lists in YAML files **without
touching anything else**. Indentation, comments, blank lines, quoting, key
order and line endings stay exactly as they were.

```yaml
- name: Bump the listening port
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.port
    value: 8080
```

```diff
 # Application settings
 server:
     host: "localhost"   # where to listen
-    port: 80
+    port: 8080
     tags:
       - web
```

## Modules

| Module | Description |
| --- | --- |
| [`yaml_edit`](#yaml_edit-set-or-remove-values) | Set or remove values, add keys at a given position, make several edits in one task. |
| [`yaml_list`](#yaml_list-add-update-or-remove-list-items) | Add, update or remove items of a list, at the end, at the start, at an index or next to another item. |

Full documentation for each module is available with `ansible-doc`, for example
`ansible-doc checkthesource.yaml_tools.yaml_list`.

## Why

The usual ways of changing part of a YAML file from Ansible all have a cost:

| Approach | Problem |
| --- | --- |
| `template` / `copy` | You have to own the whole file. |
| `slurp` + `from_yaml` + `combine` + `to_nice_yaml` | Comments are lost and the whole file is reformatted. |
| `lineinfile` / `replace` | Regular expressions don't understand YAML structure, so the same key at two levels, lists, or quoting quickly break them. |

This collection understands the structure of the file, like the second
approach, but writes changes back like the third: only the lines that change
move.

## Features

- **Lossless edits.** Only the changed value or list item is rewritten. New
  keys and items follow the indentation style already used in the file,
  including Kubernetes-style sequences (`- ` at the same level as the parent
  key).
- **Verified writes.** Every result is parsed again and must contain exactly
  the expected data, with nothing else changed. If not, the file is left
  untouched.
- **Idempotent.** Running a task twice changes nothing the second time, even
  when adding list items.
- **Safe values.** Strings that YAML could misread (`yes`, `null`, `0777`,
  `a: b`, `#x`…) are quoted, so they are read back as strings under both YAML
  1.1 (Ansible, PyYAML) and YAML 1.2.
- **Ansible-friendly.** Check mode, diff mode, `backup`, `validate`, and the
  usual `owner` / `group` / `mode` options.
- **Multi-document files** (`---`), Windows line endings, UTF-8 byte order
  marks and symbolic links are supported.

## Requirements

- ansible-core 2.16 or later on the controller.
- Python 3.6 or later and [`ruamel.yaml`](https://pypi.org/project/ruamel.yaml/)
  0.17 or later **on the managed nodes** (the hosts whose files are edited):

  ```yaml
  - name: Install ruamel.yaml
    ansible.builtin.pip:
      name: ruamel.yaml>=0.17
  ```

  Linux distributions also package it (`python3-ruamel.yaml` on Debian and
  Ubuntu, `python3-ruamel-yaml` on Fedora and RHEL with EPEL). Check that the
  packaged version is 0.17 or later; if it is older, install it with pip.

### Compatibility

| | Tested |
| --- | --- |
| ansible-core | 2.16, 2.17, 2.19, 2.21, 2.22 and the development branch |
| Python on managed nodes | 3.6 to 3.13 |
| ruamel.yaml | 0.17.21 to the latest release |

RHEL 8 managed nodes use Python 3.6 by default (`/usr/libexec/platform-python`).
ansible-core 2.16 is the last release that supports Python 3.6 on managed
nodes, so with ansible-core 2.17 or later, point `ansible_python_interpreter`
to a newer Python on those hosts (for example `python3.9` from AppStream).
On Python 3.6, `pip3 install ruamel.yaml` installs ruamel.yaml 0.18.3, which
is supported.

## Installation

From Ansible Galaxy:

```bash
ansible-galaxy collection install checkthesource.yaml_tools
```

Or in a `requirements.yml` file:

```yaml
collections:
  - name: checkthesource.yaml_tools
```

From GitHub:

```bash
ansible-galaxy collection install git+https://github.com/checkthesource/ansible-yaml-tools.git
```

To ship it with a project, install it next to your playbooks with
`ansible-galaxy collection install -r requirements.yml -p ./collections`.

## Key paths

Both modules address values with the same key path syntax:

| Key | Meaning |
| --- | --- |
| `server.port` | Key `port` inside the mapping `server` |
| `upstreams[0].host` | Key `host` of the first item of the list `upstreams` |
| `containers[-1]` | Last item of the list `containers` |
| `[0].name` | Key `name` of the first item when the document is a list |
| `annotations["example.com/owner"]` | A key that contains dots |
| `a\.b` | Same, with a backslash before the dot |
| `["metadata", "annotations", "example.com/owner"]` | List form: one item per level, never needs escaping |

Keys are matched by their text, so `ports.80` finds both `80:` and `'80':`.

## yaml_edit: set or remove values

```yaml
- name: Set a value (missing parent keys are created)
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: logging.level
    value: debug

- name: Keep a templated value an integer
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.port
    value: "{{ app_port }}"
    value_type: int

- name: Add a new key right after an existing one
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.timeout
    value: 30
    after: port

- name: Write a nested structure
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: logging.handlers.file
    value:
      level: INFO
      filename: /var/log/myapp.log

- name: Remove a key
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: features.legacy_mode
    state: absent

- name: Make several edits with a single read, check and write
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    edits:
      - key: server.port
        value: 8080
      - key: server.workers
        value: 4
      - key: debug
        state: absent
```

| Option | Default | Description |
| --- | --- | --- |
| `key` | | Key path of the value. Required unless `edits` is used. |
| `value` | | Value to set: string, number, boolean, list or dictionary. |
| `value_type` | `raw` | Convert `value` first: `raw`, `str`, `int`, `float`, `bool` or `null`. |
| `state` | `present` | `present` sets the value, `absent` removes it. |
| `create` | `true` | Create the key and missing parent mappings. |
| `after` / `before` | | Place a **new** key next to this sibling key. Existing keys are never moved. |
| `edits` | | List of edits (each with `key`, `value`, `value_type`, `state`, `create`, `after`, `before`) applied in one write. |

Returned values: `changed`, `method`, `key`, `value`, `previous_value`,
`existed`, or `results` (one entry per edit) when `edits` is used.

## yaml_list: add, update or remove list items

```yaml
- name: Add a tag at the end of a list (only once)
  checkthesource.yaml_tools.yaml_list:
    path: /etc/myapp/config.yaml
    key: server.tags
    item: admin

- name: Add a host at the start of a list
  checkthesource.yaml_tools.yaml_list:
    path: /etc/myapp/config.yaml
    key: allowed_hosts
    item: 10.0.0.5
    position: start

- name: Add a container after "web", or update it if it already exists
  checkthesource.yaml_tools.yaml_list:
    path: /srv/k8s/deployment.yaml
    key: spec.template.spec.containers
    identify_by: [name]
    after:
      name: web
    item:
      name: metrics
      image: prom/statsd-exporter:v0.27.1

- name: Remove a container by name
  checkthesource.yaml_tools.yaml_list:
    path: /srv/k8s/deployment.yaml
    key: spec.template.spec.containers
    identify_by: [name]
    item:
      name: metrics
    state: absent

- name: Insert a task at the top of a task file (the document itself is a list)
  checkthesource.yaml_tools.yaml_list:
    path: roles/web/tasks/main.yml
    index: 0
    item:
      name: Check the OS
      ansible.builtin.assert:
        that: ansible_os_family == 'Debian'
```

| Option | Default | Description |
| --- | --- | --- |
| `key` | document root | Key path of the list. |
| `item` | | The item to add or remove. |
| `state` | `present` | `present` makes sure the item is in the list, `absent` removes every matching item. |
| `identify_by` | | Fields that identify items in a list of dictionaries, for example `[name]`. A matching item that differs is **updated in place**. |
| `position` | `end` | Where to add a new item: `start` or `end`. |
| `index` | | Add a new item at this index (0 to the length of the list). |
| `after` / `before` | | Add a new item next to the first item that matches. A dictionary matches on its keys only, so `{name: web}` finds the item named `web`. |
| `create` | `true` | Create the list (and missing parents) when it doesn't exist. |

Without `identify_by`, an item matches only when it is exactly equal, so a
changed dictionary would be added as a new item. Use `identify_by` for lists of
dictionaries.

Returned values: `changed`, `method`, `action` (`added`, `created`, `updated`,
`removed` or `unchanged`), `index`, and `removed` (with `state: absent`).

## Common options

| Option | Default | Description |
| --- | --- | --- |
| `path` | *required* | YAML file to edit. It must exist. Symbolic links are followed. Alias: `dest`. |
| `document` | `0` | Document to edit in a multi-document file. |
| `edit_mode` | `auto` | See [Edit modes](#edit-modes). |
| `yaml_version` | `1.2` | How to read values such as `yes` or `0777`. See [YAML versions](#yaml-versions). |
| `backup` | `false` | Keep a timestamped copy of the original file. |
| `validate` | | Command run on the new file before it replaces the original. `%s` is the file path. |
| `owner`, `group`, `mode`, … | | The standard file attributes, as in `ansible.builtin.file`. |

## How it works

1. The file is parsed with `ruamel.yaml`, keeping the exact position of every
   key and value.
2. The module computes the data the file **should** contain after the change.
   If it already does, nothing happens (`changed: false`).
3. **Lossless edit.** Only the text of the target is replaced, inserted or
   removed. Scalars keep their quote style, and new keys and items are
   indented like their neighbours.
4. **Round-trip edit** (fallback, `edit_mode: auto` only). A few changes can't
   be made by touching a single spot, for example adding a key to an inline
   `{a: 1}` mapping or replacing a `|` block scalar. In those cases the
   document is rewritten by `ruamel.yaml`. Comments and key order are kept, but
   the indentation may be normalised.
5. **Verification.** The new text is parsed again and compared with the
   expected data, including every other document in the file. Any difference
   aborts the task and leaves the file untouched.
6. The file is written to a temporary file in the same directory, validated
   (if `validate` is set), then moved into place atomically.

### Edit modes

| Mode | Behaviour |
| --- | --- |
| `auto` | Lossless when possible, otherwise round-trip. `method` tells you which one was used. |
| `lossless` | Lossless only. The task fails if that isn't possible. |
| `roundtrip` | Always rewrite the document with `ruamel.yaml`. |

### YAML versions

YAML 1.1 (used by Ansible and PyYAML) reads `yes`, `on`, `y` as booleans and
`0777` as an octal number. YAML 1.2 reads them as strings and `777`.

- `yaml_version` decides how **existing** values are read, which matters for
  idempotence: with `1.1`, setting `true` on `enabled: yes` is a no-op; with
  `1.2` it rewrites it as `enabled: true`.
- **Written** values never depend on it: strings are quoted whenever either
  version could misread them.

## Limitations

- Only UTF-8 files are supported (with or without a byte order mark).
- Values reached through a YAML alias (`*name`), or anchored values that are
  referenced elsewhere, are refused, because changing them would change every
  place that uses them.
- Keys inherited through a merge key (`<<: *base`) can be overridden (a local
  key is added) but not removed.
- `yaml_edit` never creates list items; use `yaml_list`.
- Keys created by the modules are always strings.
- Existing keys and items are never moved by `after`, `before`, `position` or
  `index`; these options only place new ones.
- A round-trip edit does not keep `%YAML` directives, `...` document end
  markers or irregular indentation.
- Comments placed directly above a removed key are kept, except when the key
  is the only entry of its mapping or list: the parent is then written as
  `{}` or `[]` on one line, and the comments inside it are removed.

## Security

- Files are parsed with `ruamel.yaml`'s safe and round-trip loaders. They never
  create arbitrary Python objects, and custom tags such as `!vault` are kept
  as data.
- Alias bombs ("billion laughs") are rejected: the size of the data after alias
  expansion is capped at one million nodes.
- Values, items and keys can't inject extra YAML: every written scalar is
  checked to read back as exactly the requested value, and the whole result is
  verified before it is written.
- `validate` runs without a shell, so the file path can't be used to inject
  commands.
- Parse errors report a line and column only. They never echo file content,
  which may contain secrets.
- **The diff and the returned values do contain file content.** Add
  `no_log: true` to tasks that handle secrets, or run them without `--diff`.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short, with the repository checked
out under `ansible_collections/checkthesource/yaml_tools`:

```bash
pip install ansible-core ansible-lint antsibull-changelog ruamel.yaml pytest

python -m pytest tests/unit           # unit tests
ansible-test sanity --docker          # Ansible sanity tests
ansible-test integration --docker     # integration tests
ansible-lint --profile production     # best practices
```

The editing engine lives in `plugins/module_utils/yaml_core.py`. It works on
strings and never touches the filesystem, which keeps it easy to test.

## Releasing

Releases are published to Ansible Galaxy by the
[`release.yml`](.github/workflows/release.yml) workflow when a version tag is
pushed.

### One-time setup

1. On [galaxy.ansible.com](https://galaxy.ansible.com), sign in with GitHub,
   make sure you own the namespace used in `galaxy.yml`, then copy your API
   token from **Collections → API Token**.
2. In the GitHub repository, go to **Settings → Environments → New
   environment** and create an environment named `galaxy`:
   - **Required reviewers:** add yourself, so every publication waits for
     your approval.
   - **Deployment branches and tags:** choose *Selected branches and tags* and
     add the tag rule `v*`.
   - **Environment secrets:** add `GALAXY_API_KEY` with the Galaxy token.
3. Optionally, protect `v*` tags under **Settings → Rules → Rulesets** so
   that only maintainers can create them.

### Publishing a version

1. Make sure every change since the last release has a changelog fragment in
   `changelogs/fragments/` (see [CONTRIBUTING.md](CONTRIBUTING.md)).
2. Update `version` in `galaxy.yml`, then generate the changelog:

   ```bash
   antsibull-changelog release --version 1.1.0
   ```

3. Commit, then tag and push:

   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

4. The workflow runs the tests, checks that the tag matches `galaxy.yml`,
   builds the collection and waits for your approval in the **Actions** tab.
   Once approved, it publishes to Galaxy and creates the GitHub release.

Galaxy does not accept the same version twice, so every release needs a new
version number.

### How the token is protected

- It is stored in the `galaxy` environment, which only runs for `v*` tags and
  after approval. Workflows from forks and pull requests never see it.
- Only the publish job can read it, and that job doesn't check out or run
  any repository code. It only uploads the tarball built and tested by the
  previous jobs, after verifying its checksum.
- The token is passed through ansible-galaxy's configuration variables, never
  on a command line, and is masked in logs.
- Workflows use the minimum `GITHUB_TOKEN` permissions, and only GitHub's own
  actions, pinned by commit SHA and kept up to date by Dependabot.

If the token ever leaks, generate a new one on Galaxy (the old one stops
working) and update the environment secret.

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
