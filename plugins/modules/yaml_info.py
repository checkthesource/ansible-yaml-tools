#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: yaml_info
short_description: Read a value from a YAML file on the managed node
version_added: "1.1.0"
description:
  - Reads a value from a YAML file, addressed by a key path, and returns it
    with its type and whether it exists.
  - A missing key is not an error, so the result can be used in C(when) and
    C(assert) tasks.
  - It replaces the C(slurp), C(b64decode) and C(from_yaml) combination, with
    the same key paths, selectors and multi-document support as the other
    modules of the collection.
  - The file is never changed.
author:
  - checkthesource (@checkthesource)
options:
  path:
    description:
      - Path of the YAML file to read. Symbolic links are followed.
    type: path
    required: true
  key:
    description:
      - Path of the value, with the same syntax as the C(key) option of
        M(checkthesource.yaml_tools.yaml_edit), including selectors such as
        V(users[name=alice].shell).
      - Omit it to read the whole document.
      - Keys inherited through a merge key (C(<<)) are found.
    type: raw
  document:
    description:
      - "The document to read in a multi-document file, by index (V(0) is the
        first document) or by a dictionary of fields such as
        V({kind: Deployment, metadata.name: web})."
      - See the C(document) option of M(checkthesource.yaml_tools.yaml_edit).
    type: raw
    default: 0
  yaml_version:
    description:
      - YAML version used to read the file, which matters for values such as
        C(yes), C(on) or C(0777). Under V(1.2) C(yes) is a string, under
        V(1.1) a boolean.
      - A C(%YAML) directive in the file takes precedence.
    type: str
    choices: ['1.1', '1.2']
    default: '1.2'
attributes:
  check_mode:
    support: full
    description: Can run in check mode and return changed status prediction without modifying target.
  diff_mode:
    support: none
    description: Will return details on what has changed (or possibly needs changing in check_mode), when in diff mode.
  platform:
    support: full
    platforms: posix
    description: Target OS/families that can be operated against.
requirements:
  - ruamel.yaml >= 0.17 (on the managed node)
notes:
  - The task fails when the file does not exist or cannot be parsed, when the
    key path goes through a scalar, and when a selector matches several items.
  - "The returned value is file content. Use C(no_log: true) on the task when
    the file holds secrets."
  - Dates and times are returned as ISO 8601 strings.
seealso:
  - module: checkthesource.yaml_tools.yaml_edit
  - module: ansible.builtin.slurp
'''

EXAMPLES = r'''
- name: Read the port of the application
  checkthesource.yaml_tools.yaml_info:
    path: /etc/myapp/config.yaml
    key: server.port
  register: app_port

- name: Show it
  ansible.builtin.debug:
    msg: "The application listens on {{ app_port.value }}"
  when: app_port.exists

- name: Read a field of a list item chosen by its name
  checkthesource.yaml_tools.yaml_info:
    path: /etc/myapp/users.yaml
    key: users[name=alice].shell
  register: shell

- name: Read the replicas of a Deployment in a file with several manifests
  checkthesource.yaml_tools.yaml_info:
    path: app.yaml
    document:
      kind: Deployment
      metadata.name: web
    key: spec.replicas
  register: replicas

- name: Check a setting before deploying
  ansible.builtin.assert:
    that:
      - replicas.exists
      - replicas.value >= 2
'''

RETURN = r'''
path:
  description: Path of the file that was read (the link target when O(path) is a symbolic link).
  returned: always
  type: str
  sample: /etc/myapp/config.yaml
exists:
  description: Whether the key exists.
  returned: always
  type: bool
  sample: true
value:
  description: The value. Null when the key does not exist, or when it exists and is null.
  returned: always
  type: raw
  sample: 8080
type:
  description:
    - Type of the value, V(str), V(int), V(float), V(bool), V(null), V(dict),
      V(list), V(timestamp) or V(other).
    - Null when the key does not exist.
  returned: always
  type: str
  sample: int
document:
  description: Index of the document that was read.
  returned: always
  type: int
  sample: 0
documents:
  description: Number of documents in the file.
  returned: always
  type: int
  sample: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.checkthesource.yaml_tools.plugins.module_utils.yaml_core import (
    YamlEditError,
    parse_key,
    read_yaml_value,
    run_file_read,
)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(type='path', required=True),
            key=dict(type='raw', no_log=False),
            document=dict(type='raw', default=0),
            yaml_version=dict(type='str', default='1.2', choices=['1.1', '1.2']),
        ),
        supports_check_mode=True,
    )
    params = module.params

    try:
        parts = parse_key(params['key'], allow_empty=True)
    except YamlEditError as e:
        module.fail_json(msg=str(e))

    def read(text):
        return read_yaml_value(text, parts, document=params['document'], yaml_version=params['yaml_version'])

    run_file_read(module, read, {})


if __name__ == '__main__':
    main()
