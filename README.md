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
| [`yaml_merge`](#yaml_merge-merge-a-dictionary) | Deep-merge a dictionary into the file: only the differences are written. |
| [`yaml_info`](#yaml_info-read-a-value) | Read a value, its type and whether it exists, without changing the file. |

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
- **Select items and documents by content.** `users[name=alice].shell`
  reaches a field of a list item without knowing its index, and
  `document: {kind: Deployment, metadata.name: web}` picks one manifest in a
  multi-document file.
- **Typed values from templates.** Before ansible-core 2.19, Ansible passes
  every templated number as a string. The modules write `"{{ port }}"` as
  `8080`, not `'8080'`, so files stay clean and tasks stay idempotent.
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

Every module addresses values with the same key path syntax:

| Key | Meaning |
| --- | --- |
| `server.port` | Key `port` inside the mapping `server` |
| `upstreams[0].host` | Key `host` of the first item of the list `upstreams` |
| `containers[-1]` | Last item of the list `containers` |
| `[0].name` | Key `name` of the first item when the document is a list |
| `annotations["example.com/owner"]` | A key that contains dots |
| `a\.b` | Same, with a backslash before the dot |
| `["metadata", "annotations", "example.com/owner"]` | List form: one item per level, never needs escaping |
| `users[name=alice].shell` | Key `shell` of the item of `users` whose `name` is `alice` |
| `containers[name=web,image="nginx:1.27"]` | Several conditions; quote values that contain `,` or `]` |
| `items[metadata.name=web]` | A nested field |
| `["users", {"name": "alice"}, "shell"]` | A selector in the list form |

Keys are matched by their text, so `ports.80` finds both `80:` and `'80':`.
Selector values are compared the same way, so `[port=80]` matches `port: 80`
and `port: '80'`.

A selector must match **exactly one** item. The task fails when several items
match, and also when none does, except when removing or renaming (there is
then nothing to do). Selectors don't create items: use `yaml_list` to add them.

## yaml_edit: set or remove values

```yaml
- name: Set a value (missing parent keys are created)
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: logging.level
    value: debug

- name: Change one field of a list item chosen by its name
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/users.yaml
    key: users[name=alice].shell
    value: /bin/zsh

- name: Rename a key (its value, comments and position are kept)
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.listen
    rename_to: bind

- name: Edit one manifest of a multi-document file
  checkthesource.yaml_tools.yaml_edit:
    path: app.yaml
    document:
      kind: Deployment
      metadata.name: web
    key: spec.replicas
    value: "{{ replicas }}"

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
| `value_type` | `raw` | Convert `value` first: `raw`, `str`, `int`, `float`, `bool` or `null`. Takes precedence over `infer_types`. |
| `state` | `present` | `present` sets the value, `absent` removes it. |
| `create` | `true` | Create the key and missing parent mappings. |
| `after` / `before` | | Place a **new** key next to this sibling key. Existing keys are never moved. |
| `rename_to` | | Rename the key, keeping its value and position. Nothing happens when the key doesn't exist (already renamed). |
| `edits` | | List of edits (each with `key`, `value`, `value_type`, `state`, `create`, `after`, `before`, `rename_to`) applied in one write. |

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

- name: Add a member to a list inside the item named "web"
  checkthesource.yaml_tools.yaml_list:
    path: /etc/myapp/groups.yaml
    key: groups[name=web].members
    item: alice

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

With `identify_by`, the matching item is replaced as a whole. To change a
single field of an item and leave the others alone, use `yaml_edit` with a
selector, for example `key: users[name=alice].shell`.

Returned values: `changed`, `method`, `action` (`added`, `created`, `updated`,
`removed` or `unchanged`), `index`, and `removed` (with `state: absent`).

## yaml_merge: merge a dictionary

```yaml
- name: Apply a block of settings (only the differences are written)
  checkthesource.yaml_tools.yaml_merge:
    path: /etc/myapp/config.yaml
    key: server
    value:
      port: 8080
      tls:
        enabled: true
        certificate: /etc/ssl/myapp.pem

- name: Add hosts without removing the existing ones
  checkthesource.yaml_tools.yaml_merge:
    path: /etc/myapp/config.yaml
    value:
      allowed_hosts: [10.0.0.5, 10.0.0.6]
    list_merge: append
```

```diff
 server:
-  port: 80          # public port
+  port: 8080          # public port
   tls:
-    enabled: false
+    enabled: true
+    certificate: /etc/ssl/myapp.pem
```

The merge works like the `combine` filter with `recursive=true`: missing keys
are added, nested dictionaries are merged, other values are replaced, and keys
of the file that aren't in `value` are kept. Each change is a small verified
edit, so the rest of the file doesn't move.

| Option | Default | Description |
| --- | --- | --- |
| `key` | document root | Key path of the mapping to merge into. Created when missing. |
| `value` | *required* | The dictionary to merge. |
| `list_merge` | `replace` | When both sides hold a list: `replace` it, `keep` it, or add the missing items with `append` or `prepend`. Items are never added twice. |
| `create` | `true` | Create the mapping at `key` when it doesn't exist. |

Returned values: `changed`, `method`, `changes` (the key paths that were added
or changed).

## yaml_info: read a value

```yaml
- name: Read the replicas of a Deployment
  checkthesource.yaml_tools.yaml_info:
    path: app.yaml
    document:
      kind: Deployment
    key: spec.replicas
  register: replicas

- name: Check it
  ansible.builtin.assert:
    that:
      - replicas.exists
      - replicas.value >= 2
```

It replaces the `slurp` + `b64decode` + `from_yaml` combination, with the same
key paths and selectors as the other modules. A missing key isn't an error:
`exists` is `false`.

Options: `path`, `key` (omit it for the whole document), `document`,
`yaml_version`. Returned values: `exists`, `value`, `type` (`str`, `int`,
`float`, `bool`, `null`, `dict`, `list`, `timestamp`), `document` (the index
that was read) and `documents` (how many the file has).

## Common options

These options are shared by `yaml_edit`, `yaml_list` and `yaml_merge`
(`yaml_info` takes `path`, `document` and `yaml_version`).

| Option | Default | Description |
| --- | --- | --- |
| `path` | *required* | YAML file to edit. It must exist. Symbolic links are followed. Alias: `dest`. |
| `document` | `0` | Document to edit in a multi-document file: its index, or a dictionary of fields such as `{kind: Deployment, metadata.name: web}` that must match a single document. |
| `infer_types` | `true` | Write strings that are plainly integers or booleans (`"8080"`, `"true"`) as numbers and booleans. See [Templated values](#templated-values). |
| `edit_mode` | `auto` | See [Edit modes](#edit-modes). |
| `yaml_version` | `1.2` | How to read values such as `yes` or `0777`. See [YAML versions](#yaml-versions). |
| `backup` | `false` | Keep a timestamped copy of the original file. |
| `validate` | | Command run on the new file before it replaces the original. `%s` is the file path. |
| `owner`, `group`, `mode`, … | | The standard file attributes, as in `ansible.builtin.file`. |

### Templated values

Before ansible-core 2.19, Ansible renders every templated number as a string:
`port: "{{ app_port }}"` reaches the module as `"8080"`, even with `| int`.
Written as is, it would become `port: '8080'` in the file, and it would not be
recognised as equal to an existing `port: 8080`, so `yaml_list` would add a
duplicate item.

With `infer_types: true` (the default), such strings are converted before
they are written or compared:

| Given | Written as |
| --- | --- |
| `"8080"`, `"0"`, `"-7"` | `8080`, `0`, `-7` |
| `"true"`, `"False"` | `true`, `false` |
| `"0755"`, `"1.10"`, `"yes"`, `"1e3"` and any other string | a string, unchanged |

Floats are never inferred, because `"1.10"` is more often a version than a
number. To force a type, use `value_type` with `yaml_edit`. To write such
strings as strings, set `infer_types: false`.

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
- Selectors look at the fields written in each item. Fields inherited through
  a merge key (`<<`) are not considered.
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

Releases are built, tested and published to Galaxy by a GitHub Actions
workflow, and each publication needs a maintainer's approval. The tarball and
its SHA-256 checksum are attached to every
[GitHub release](https://github.com/checkthesource/ansible-yaml-tools/releases).

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

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
