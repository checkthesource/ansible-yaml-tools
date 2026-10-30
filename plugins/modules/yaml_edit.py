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
      - "An item of a list of dictionaries can be chosen by the value of one of
        its fields instead of its index: V(users[name=alice].shell) is the
        C(shell) of the item whose C(name) is C(alice). Several conditions are
        separated by commas, fields can be nested, and values can be quoted:
        V(containers[name=web,image=\"nginx:1.27\"].ports)."
      - "A selector must match exactly one item: the task fails when several
        items match, and also when none does, except with O(state=absent) or
        O(rename_to), where there is then nothing to do. Values are compared as
        text, like keys, so V([port=80]) matches C(port: 80) and C(port: '80')."
      - "As a list: one item per level, strings for mapping keys, integers
        for list indexes and dictionaries for selectors, for example
        V([\"annotations\", \"example.com/owner\"]), V([\"ports\", 0]) or
        V([\"users\", {\"name\": \"alice\"}, \"shell\"]). Mapping keys
        in this form never need escaping."
      - Keys are matched by their text, so V(ports.80) matches both C(80:) and C('80':).
      - Required unless O(edits) is used.
    type: raw
  value:
    description:
      - The value to set when O(state=present). It can be a string, number,
        boolean, list or dictionary.
      - Required when O(state=present), unless O(value_type=null) or
        O(rename_to) is used.
    type: raw
  value_type:
    description:
      - Convert O(value) to this type before writing it.
      - V(raw) keeps the value as Ansible passes it, except that strings that
        are plainly integers or booleans are written as such when O(infer_types=true)
        (the default).
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
  rename_to:
    description:
      - Rename the key at O(key) to this name. Its value, its comments and its
        position in the mapping are kept.
      - This is the new name of the key only, not a path; the key stays in the
        same mapping.
      - Nothing changes when O(key) does not exist, for example because it has
        already been renamed. The task fails when a key with the new name
        already exists.
      - Mutually exclusive with O(value), O(after), O(before), O(state=absent)
        and O(value_type) other than V(raw).
    type: str
    version_added: 1.1.0
  edits:
    description:
      - A list of edits applied in order, in a single read, verification and
        write of the file.
      - Each item takes the same options as the module itself.
      - Mutually exclusive with O(key), O(value), O(after), O(before) and O(rename_to).
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
      rename_to:
        description: New name of the key, see O(rename_to).
        type: str
        version_added: 1.1.0
extends_documentation_fragment:
  - ansible.builtin.files
  - checkthesource.yaml_tools.common
notes:
  - Keys inherited through a merge key (C(<<)) can be overridden; a local key is
    then added. They cannot be removed.
  - Keys created by this module are always strings.
seealso:
  - module: checkthesource.yaml_tools.yaml_list
  - module: checkthesource.yaml_tools.yaml_merge
  - module: checkthesource.yaml_tools.yaml_info
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

- name: Change the shell of the user named "alice", without touching her other fields
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/users.yaml
    key: users[name=alice].shell
    value: /bin/zsh

- name: Change the image of the container named "web"
  checkthesource.yaml_tools.yaml_edit:
    path: deployment.yaml
    key: spec.template.spec.containers[name=web].image
    value: nginx:1.27

- name: Edit the Deployment named "web" in a file with several manifests
  checkthesource.yaml_tools.yaml_edit:
    path: app.yaml
    document:
      kind: Deployment
      metadata.name: web
    key: spec.replicas
    value: 3

- name: Rename a key (its value, comments and position are kept)
  checkthesource.yaml_tools.yaml_edit:
    path: /etc/myapp/config.yaml
    key: server.listen
    rename_to: bind

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
  description:
    - The key path, split into its parts.
    - 'Selectors are returned as dictionaries, for example C({"name": "web"}).'
  returned: when O(edits) is not used
  type: list
  elements: raw
  sample: ["server", "port"]
value:
  description:
    - The value that was written, after O(value_type) conversion.
    - Null when O(state=absent) or O(rename_to) is used.
  returned: when O(edits) is not used
  type: raw
  sample: 8080
previous_value:
  description:
    - The value before the edit. Null when the key did not exist.
    - With O(rename_to), the value of the renamed key.
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
      description: The value written, or null when removing or renaming.
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
    infer_types,
    parse_key,
    parts_to_json,
    rename_key_text,
    resolve_document,
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
    rename_to=dict(type='str'),
)


def prepare_edit(options, infer=False):
    """Validate one edit and return (key parts, value)."""
    parts = parse_key(options['key'])
    value = None
    if options['rename_to'] is not None:
        conflicts = [name for name in ('value', 'after', 'before') if options[name] is not None]
        if options['state'] == 'absent':
            conflicts.append('state=absent')
        if options['value_type'] != 'raw':
            conflicts.append('value_type')
        if conflicts:
            raise YamlEditError('rename_to cannot be used with %s' % ', '.join(conflicts))
        if not options['rename_to']:
            raise YamlEditError('rename_to must not be empty')
    elif options['state'] == 'present':
        if options['value'] is None and options['value_type'] != 'null':
            raise YamlEditError('value is required when state=present (use value_type=null to write null)')
        value = convert_value(options['value'], options['value_type'])
        if infer and options['value_type'] == 'raw':
            value = infer_types(value)
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
        mutually_exclusive=[('edits', name) for name in ('key', 'value', 'after', 'before', 'rename_to')],
        required_one_of=[('key', 'edits')],
    )
    params = module.params
    batch = params['edits'] is not None
    result = {}

    try:
        if batch:
            if not params['edits']:
                raise YamlEditError('edits must not be empty')
            prepared = [prepare_edit(options, params['infer_types']) + (options,) for options in params['edits']]
        else:
            prepared = [prepare_edit(params, params['infer_types']) + (params,)]
            result['key'] = parts_to_json(prepared[0][0])
    except YamlEditError as e:
        module.fail_json(msg=str(e), **result)

    def edit(text):
        results = []
        # Resolved once, so that every edit works on the same document.
        document = resolve_document(text, params['document'], params['yaml_version'])
        common = dict(document=document, edit_mode=params['edit_mode'], yaml_version=params['yaml_version'])
        for number, (parts, value, options) in enumerate(prepared):
            try:
                if options['rename_to'] is not None:
                    res = rename_key_text(text, parts, options['rename_to'], **common)
                    res.info['previous'] = res.info['value']
                    res.info['value'] = None
                else:
                    res = edit_yaml_text(
                        text, parts, state=options['state'], value=value, create=options['create'],
                        after=options['after'], before=options['before'], **common)
            except YamlEditError as e:
                if batch:
                    raise YamlEditError('edits[%d] (%s): %s' % (number, options['key'], e))
                raise
            text = res.text
            results.append(dict(key=parts_to_json(parts), changed=res.changed, method=res.method, value=res.info['value'],
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
