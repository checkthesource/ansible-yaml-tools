#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: yaml_edit
short_description: Set or remove values in a YAML file without reformatting it
version_added: "1.0.0"
description:
  - Sets or removes values in a YAML file, addressed by key paths.
  - "Edits are B(lossless) whenever possible: only the bytes of the changed value
    are rewritten. Indentation, comments, blank lines, quoting, key order, line
    endings and everything else in the file stay exactly as they were."
  - When a lossless edit is not possible (for example when adding a key to an
    inline C({...}) mapping), the module can fall back to a B(round-trip) edit
    with C(ruamel.yaml), which keeps comments and key order but may normalise
    the formatting of the file. This is controlled by O(edit_mode).
  - Several edits can be made in one task with O(edits). The file is then read,
    verified and written only once.
  - To add, update or remove items of a list, use M(checkthesource.yaml_tools.yaml_list).
author:
  - checkthesource (@checkthesource)
options:
  key:
    description:
      - Path of the value to edit.
      - "As a string: keys separated by dots, with list indexes in brackets,
        for example V(server.ports[0]) or V(spec.containers[-1].image)."
      - "Keys containing dots or brackets can be quoted in brackets,
        for example V(annotations[\"example.com/owner\"]). A dot can also be
        escaped with a backslash: V(a\\\\.b)."
      - "As a list: one item per level, strings for mapping keys and integers
        for list indexes, for example V([\"annotations\", \"example.com/owner\"])
        or V([\"ports\", 0]). This form never needs escaping."
      - Keys are matched by their text, so V(ports.80) matches both C(80:) and C('80':).
      - Required unless O(edits) is used.
    type: raw
  value:
    description:
      - The value to set when O(state=present). It can be a string, number,
        boolean, list or dictionary.
      - Required when O(state=present), unless O(value_type=null).
    type: raw
  value_type:
    description:
      - Convert O(value) to this type before writing it.
      - V(raw) keeps the value exactly as Ansible passes it.
      - "Useful when a templated value arrives as a string, for example
        C(value: \"{{ port }}\") with O(value_type=int)."
      - V(null) writes a YAML null. O(value) must then be omitted or null.
    type: str
    choices: [raw, str, int, float, bool, 'null']
    default: raw
  state:
    description:
      - V(present) sets the value, V(absent) removes the key or list item.
    type: str
    choices: [present, absent]
    default: present
  create:
    description:
      - When O(state=present) and the key does not exist, create it, together
        with any missing parent mappings.
      - When V(false), a missing key is an error.
      - Missing list items are never created; use M(checkthesource.yaml_tools.yaml_list).
    type: bool
    default: true
  after:
    description:
      - When the key is created, place it right after this sibling key
        instead of at the end of its mapping.
      - The parent mapping and the sibling key must exist.
      - Has no effect when the key already exists; existing keys are never moved.
      - Mutually exclusive with O(before).
    type: str
  before:
    description:
      - When the key is created, place it right before this sibling key.
      - Same rules as O(after).
    type: str
  edits:
    description:
      - A list of edits applied in order, in a single read, verification and
        write of the file.
      - Each item takes the same options as the module itself.
      - Mutually exclusive with O(key), O(value), O(after) and O(before).
    type: list
    elements: dict
    suboptions:
      key:
        description: Path of the value, see O(key).
        type: raw
        required: true
      value:
        description: The value to set, see O(value).
        type: raw
      value_type:
        description: Conversion of O(edits[].value), see O(value_type).
        type: str
        choices: [raw, str, int, float, bool, 'null']
        default: raw
      state:
        description: V(present) or V(absent), see O(state).
        type: str
        choices: [present, absent]
        default: present
      create:
        description: Create missing keys, see O(create).
        type: bool
        default: true
      after:
        description: Sibling key to place a new key after, see O(after).
        type: str
      before:
        description: Sibling key to place a new key before, see O(before).
        type: str
extends_documentation_fragment:
  - ansible.builtin.files
  - checkthesource.yaml_tools.common
notes:
  - Keys inherited through a merge key (C(<<)) can be overridden; a local key is
    then added. They cannot be removed.
  - Keys created by this module are always strings.
seealso:
  - module: checkthesource.yaml_tools.yaml_list
  - module: ansible.builtin.lineinfile
  - module: ansible.builtin.replace
'''

EXAMPLES = r'''
- name: Change a value (only the value is rewritten)
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.port
    value: 8080

- name: Set a value from a template and keep it an integer
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.port
    value: "{{ app_port }}"
    value_type: int

- name: Add a key right after another one
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.timeout
    value: 30
    after: port

- name: Use a key that contains dots
  checkthesource.yaml_tools.yaml_edit:
    path: deployment.yaml
    key: ["metadata", "annotations", "example.com/owner"]
    value: platform-team

- name: Add a nested dictionary (missing parents are created)
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: logging.handlers.file
    value:
      level: INFO
      filename: /var/log/myapp.log

- name: Remove a key
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: debug
    state: absent

- name: Make several changes with a single write
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    edits:
      - key: server.port
        value: 8080
      - key: server.workers
        value: "{{ ansible_processor_vcpus }}"
        value_type: int
      - key: debug
        state: absent

- name: Never change the formatting, fail instead
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: features.beta
    value: true
    edit_mode: lossless

- name: Validate the file and keep a backup
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.workers
    value: 4
    backup: true
    validate: /usr/local/bin/myapp check-config --file %s
    owner: myapp
    group: myapp
    mode: "0640"
'''

RETURN = r'''
path:
  description: Path of the edited file (the link target when O(path) is a symbolic link).
  returned: always
  type: str
  sample: /etc/myapp/config.yaml
method:
  description:
    - How the file was edited. V(lossless) means only the changed values were
      rewritten. V(roundtrip) means the document was rewritten by C(ruamel.yaml),
      for at least one edit.
    - Null when nothing changed.
  returned: always
  type: str
  sample: lossless
key:
  description: The key path, split into its parts.
  returned: when O(edits) is not used
  type: list
  elements: raw
  sample: ["server", "port"]
value:
  description: The value that was written, after O(value_type) conversion. Null when O(state=absent).
  returned: when O(edits) is not used
  type: raw
  sample: 8080
previous_value:
  description: The value before the edit. Null when the key did not exist.
  returned: when O(edits) is not used
  type: raw
  sample: 80
existed:
  description: Whether the key existed before the edit.
  returned: when O(edits) is not used
  type: bool
  sample: true
results:
  description: One entry per item of O(edits), in the same order.
  returned: when O(edits) is used
  type: list
  elements: dict
  contains:
    key:
      description: The key path, split into its parts.
      type: list
      elements: raw
    changed:
      description: Whether this edit changed the file.
      type: bool
    method:
      description: V(lossless), V(roundtrip), or null when this edit changed nothing.
      type: str
    value:
      description: The value written, or null when removing.
      type: raw
    previous_value:
      description: The value before this edit.
      type: raw
    existed:
      description: Whether the key existed before this edit.
      type: bool
  sample:
    - key: ["server", "port"]
      changed: true
      method: lossless
      value: 8080
      previous_value: 80
      existed: true
backup_file:
  description: Name of the backup file that was created.
  returned: changed and O(backup=true)
  type: str
  sample: /etc/myapp/config.yaml.12345.2026-10-29@12:00:00~
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.checkthesource.yaml_tools.plugins.module_utils.yaml_core import (
    EditResult,
    YamlEditError,
    combine_methods,
    common_argument_spec,
    convert_value,
    edit_yaml_text,
    parse_key,
    run_file_edit,
)

EDIT_OPTIONS = dict(
    key=dict(type='raw', no_log=False),
    value=dict(type='raw'),
    value_type=dict(type='str', default='raw', choices=['raw', 'str', 'int', 'float', 'bool', 'null']),
    state=dict(type='str', default='present', choices=['present', 'absent']),
    create=dict(type='bool', default=True),
    after=dict(type='str'),
    before=dict(type='str'),
)


def prepare_edit(options):
    """Validate one edit and return (key parts, value)."""
    parts = parse_key(options['key'])
    value = None
    if options['state'] == 'present':
        if options['value'] is None and options['value_type'] != 'null':
            raise YamlEditError('value is required when state=present (use value_type=null to write null)')
        value = convert_value(options['value'], options['value_type'])
    elif options['after'] is not None or options['before'] is not None:
        raise YamlEditError('after and before can only be used with state=present')
    if options['after'] is not None and options['before'] is not None:
        raise YamlEditError('after and before are mutually exclusive')
    return parts, value


def main():
    edit_suboptions = dict(EDIT_OPTIONS)
    edit_suboptions['key'] = dict(type='raw', required=True, no_log=False)
    argument_spec = common_argument_spec()
    argument_spec.update(EDIT_OPTIONS)
    argument_spec['edits'] = dict(type='list', elements='dict', options=edit_suboptions)

    module = AnsibleModule(
        argument_spec=argument_spec,
        add_file_common_args=True,
        supports_check_mode=True,
        mutually_exclusive=[('edits', name) for name in ('key', 'value', 'after', 'before')],
        required_one_of=[('key', 'edits')],
    )
    params = module.params
    batch = params['edits'] is not None
    result = {}

    try:
        if batch:
            if not params['edits']:
                raise YamlEditError('edits must not be empty')
            prepared = [prepare_edit(options) + (options,) for options in params['edits']]
        else:
            prepared = [prepare_edit(params) + (params,)]
            result['key'] = prepared[0][0]
    except YamlEditError as e:
        module.fail_json(msg=str(e), **result)

    def edit(text):
        results = []
        for number, (parts, value, options) in enumerate(prepared):
            try:
                res = edit_yaml_text(
                    text, parts, state=options['state'], value=value, document=params['document'],
                    edit_mode=params['edit_mode'], yaml_version=params['yaml_version'],
                    create=options['create'], after=options['after'], before=options['before'])
            except YamlEditError as e:
                if batch:
                    raise YamlEditError('edits[%d] (%s): %s' % (number, options['key'], e))
                raise
            text = res.text
            results.append(dict(key=parts, changed=res.changed, method=res.method, value=res.info['value'],
                                previous_value=res.info['previous'], existed=res.info['existed']))
        if batch:
            result['results'] = results
        else:
            single = results[0]
            result.update(value=single['value'], previous_value=single['previous_value'],
                          existed=single['existed'])
        changed = any(r['changed'] for r in results)
        return EditResult(text, changed, combine_methods(*[r['method'] for r in results]))

    run_file_edit(module, edit, result)


if __name__ == '__main__':
    main()
