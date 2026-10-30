#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: yaml_merge
short_description: Merge a dictionary into a YAML file without reformatting it
version_added: "1.1.0"
description:
  - Deep-merges a dictionary into a mapping of a YAML file, the way the
    C(ansible.builtin.combine) filter merges dictionaries with C(recursive=true).
  - Keys that are missing are added, nested dictionaries are merged key by key,
    and other values are replaced when they differ. Keys of the file that are
    not in O(value) are kept.
  - How lists are merged is chosen with O(list_merge).
  - "Edits are B(lossless) whenever possible: only the lines of the added or
    changed values are rewritten, and each change is verified as with
    M(checkthesource.yaml_tools.yaml_edit)."
  - Use this module to apply a block of settings in one task. To set a single
    value, M(checkthesource.yaml_tools.yaml_edit) is simpler.
author:
  - checkthesource (@checkthesource)
options:
  key:
    description:
      - Path of the mapping to merge into, with the same syntax as the C(key)
        option of M(checkthesource.yaml_tools.yaml_edit), including selectors
        such as V(containers[name=web]).
      - Omit it to merge into the top of the document.
      - When the path does not exist, it is created with O(value) as its value
        (see O(create)). When it holds a scalar or a list, that value is
        replaced by O(value).
    type: raw
  value:
    description:
      - The dictionary to merge.
    type: dict
    required: true
  list_merge:
    description:
      - What to do when a key holds a list both in the file and in O(value).
      - V(replace) replaces the list of the file by the list of O(value).
      - V(keep) keeps the list of the file as it is.
      - V(append) adds the items of O(value) that are not in the list yet at
        its end, and V(prepend) at its start, in the order of O(value).
      - Items already in the list are never added twice, so every choice is
        idempotent.
      - Items of lists are compared as a whole. To update a dictionary inside a
        list by one of its fields, use M(checkthesource.yaml_tools.yaml_list)
        with C(identify_by), or M(checkthesource.yaml_tools.yaml_edit) with a
        selector.
    type: str
    choices: [replace, keep, append, prepend]
    default: replace
  create:
    description:
      - When the mapping at O(key) does not exist, create it, together with any
        missing parent mappings.
      - When V(false), a missing mapping is an error.
    type: bool
    default: true
extends_documentation_fragment:
  - ansible.builtin.files
  - checkthesource.yaml_tools.common
notes:
  - The merge never removes keys. Use M(checkthesource.yaml_tools.yaml_edit)
    with O(checkthesource.yaml_tools.yaml_edit#module:state=absent) for that.
  - New keys are added at the end of their mapping.
seealso:
  - module: checkthesource.yaml_tools.yaml_edit
  - module: checkthesource.yaml_tools.yaml_list
  - plugin: ansible.builtin.combine
    plugin_type: filter
'''

EXAMPLES = r'''
- name: Apply a block of settings (only the differences are written)
  checkthesource.yaml_tools.yaml_merge:
    path: /etc/myapp/config.yaml
    key: server
    value:
      port: 8080
      tls:
        enabled: true
        certificate: /etc/ssl/myapp.pem

- name: Merge into the top of the document
  checkthesource.yaml_tools.yaml_merge:
    path: /etc/myapp/config.yaml
    value:
      logging:
        level: INFO

- name: Add allowed hosts without removing the existing ones
  checkthesource.yaml_tools.yaml_merge:
    path: /etc/myapp/config.yaml
    value:
      allowed_hosts:
        - 10.0.0.5
        - 10.0.0.6
    list_merge: append

- name: Add resource limits to the container named "web"
  checkthesource.yaml_tools.yaml_merge:
    path: deployment.yaml
    key: spec.template.spec.containers[name=web]
    value:
      resources:
        limits:
          cpu: 500m
          memory: 256Mi
'''

RETURN = r'''
path:
  description: Path of the edited file (the link target when O(path) is a symbolic link).
  returned: always
  type: str
  sample: /etc/myapp/config.yaml
changes:
  description: Key paths of the values that were added or changed, split into their parts.
  returned: always
  type: list
  elements: list
  sample: [["server", "port"], ["server", "tls"]]
method:
  description:
    - How the file was edited. V(lossless) means only the changed values were
      rewritten. V(roundtrip) means the document was rewritten by C(ruamel.yaml),
      for at least one change.
    - Null when nothing changed.
  returned: always
  type: str
  sample: lossless
backup_file:
  description: Name of the backup file that was created.
  returned: changed and O(backup=true)
  type: str
  sample: /etc/myapp/config.yaml.12345.2026-10-29@12:00:00~
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.checkthesource.yaml_tools.plugins.module_utils.yaml_core import (
    LIST_MERGE_CHOICES,
    YamlEditError,
    common_argument_spec,
    infer_types,
    merge_yaml_text,
    parse_key,
    resolve_document,
    run_file_edit,
)


def main():
    argument_spec = common_argument_spec()
    argument_spec.update(
        key=dict(type='raw', no_log=False),
        value=dict(type='dict', required=True),
        list_merge=dict(type='str', default='replace', choices=list(LIST_MERGE_CHOICES)),
        create=dict(type='bool', default=True),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        add_file_common_args=True,
        supports_check_mode=True,
    )
    params = module.params
    result = dict(changes=[])

    try:
        parts = parse_key(params['key'], allow_empty=True)
    except YamlEditError as e:
        module.fail_json(msg=str(e), **result)

    def edit(text):
        document = resolve_document(text, params['document'], params['yaml_version'])
        value = infer_types(params['value']) if params['infer_types'] else params['value']
        res = merge_yaml_text(text, parts, value, list_merge=params['list_merge'],
                              create=params['create'], document=document, edit_mode=params['edit_mode'],
                              yaml_version=params['yaml_version'])
        result['changes'] = res.info['changes']
        return res

    run_file_edit(module, edit, result)


if __name__ == '__main__':
    main()
