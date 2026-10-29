#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: yaml_list
short_description: Add, update or remove items of a list in a YAML file without reformatting it
version_added: "1.0.0"
description:
  - Makes sure an item is present in, or absent from, a list in a YAML file.
  - "The module is idempotent: an item that is already present is not added
    again, so running the task twice does not duplicate it."
  - Items can be added at the end, at the start, at an index, or next to
    another item.
  - With O(identify_by), items of a list of dictionaries are identified by
    some of their fields (for example C(name)). A matching item that differs
    is updated in place instead of being added again.
  - "Edits are B(lossless) whenever possible: only the lines of the added,
    updated or removed item change. New items follow the indentation of the
    existing ones."
  - To set or remove values in mappings, use M(checkthesource.yaml_tools.yaml_edit).
author:
  - checkthesource (@checkthesource)
options:
  key:
    description:
      - Path of the list, with the same syntax as the C(key) option of
        M(checkthesource.yaml_tools.yaml_edit), for example V(server.tags) or
        V(spec.template.spec.containers).
      - Omit it when the document itself is a list (for example a task file).
    type: raw
  item:
    description:
      - The item to add or remove. It can be a string, number, boolean,
        list or dictionary.
    type: raw
    required: true
  state:
    description:
      - V(present) makes sure the item is in the list.
      - V(absent) removes every matching item.
    type: str
    choices: [present, absent]
    default: present
  identify_by:
    description:
      - Fields that identify an item in a list of dictionaries, for example
        V([name]). O(item) must be a dictionary that contains them.
      - "With O(state=present): when an item with the same values for these
        fields exists, it is replaced by O(item) if it differs, and nothing
        changes otherwise. When none exists, O(item) is added."
      - With O(state=absent), every item with the same values for these
        fields is removed, whatever its other fields.
      - Without this option, an item matches only when it is exactly equal
        to O(item).
      - When several items match with O(state=present), the task fails.
    type: list
    elements: str
  position:
    description:
      - Where to add a new item, V(end) (the default) or V(start).
      - Mutually exclusive with O(index), O(after) and O(before).
      - Only used when the item is added; existing items are never moved.
    type: str
    choices: [start, end]
  index:
    description:
      - Add a new item at this index, from V(0) (first) to the length of the
        list (last).
      - Only used when the item is added.
    type: int
  after:
    description:
      - Add a new item right after the first item that matches this value.
      - "A dictionary matches every item that has the same values for its keys,
        so V({name: web}) matches the item whose C(name) is C(web)."
      - The task fails when no item matches.
      - Only used when the item is added.
    type: raw
  before:
    description:
      - Add a new item right before the first item that matches this value.
      - Same rules as O(after).
    type: raw
  create:
    description:
      - When the list does not exist (or is null), create it with O(item) as its
        only item. Missing parent mappings are created too.
      - When V(false), a missing list is an error.
    type: bool
    default: true
extends_documentation_fragment:
  - ansible.builtin.files
  - checkthesource.yaml_tools.common
seealso:
  - module: checkthesource.yaml_tools.yaml_edit
'''

EXAMPLES = r'''
- name: Add a tag at the end of a list (once)
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

- name: Add a container after the one named "web", or update it if it exists
  checkthesource.yaml_tools.yaml_list:
    path: /srv/k8s/deployment.yaml
    key: spec.template.spec.containers
    identify_by: [name]
    after:
      name: web
    item:
      name: metrics
      image: prom/statsd-exporter:v0.27.1
      ports:
        - containerPort: 9102

- name: Remove a container by name
  checkthesource.yaml_tools.yaml_list:
    path: /srv/k8s/deployment.yaml
    key: spec.template.spec.containers
    identify_by: [name]
    item:
      name: metrics
    state: absent

- name: Insert a task at a given position in a task file (the document is a list)
  checkthesource.yaml_tools.yaml_list:
    path: roles/web/tasks/main.yml
    index: 0
    item:
      name: Check the OS
      ansible.builtin.assert:
        that: ansible_os_family == 'Debian'
'''

RETURN = r'''
path:
  description: Path of the edited file (the link target when O(path) is a symbolic link).
  returned: always
  type: str
  sample: /etc/myapp/config.yaml
action:
  description:
    - What happened. V(added) when the item was added, V(created) when the
      list was created, V(updated) when a matching item was replaced,
      V(removed) when items were removed, V(unchanged) otherwise.
  returned: always
  type: str
  sample: added
index:
  description: Index of the added, updated or already present item.
  returned: when O(state=present)
  type: int
  sample: 2
removed:
  description: Number of items removed.
  returned: when O(state=absent)
  type: int
  sample: 1
method:
  description:
    - How the file was edited. V(lossless) means only the lines of the changed
      items were rewritten. V(roundtrip) means the document was rewritten by
      C(ruamel.yaml).
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
    YamlEditError,
    common_argument_spec,
    ensure_list_item,
    parse_key,
    remove_list_items,
    run_file_edit,
)


def main():
    argument_spec = common_argument_spec()
    argument_spec.update(
        key=dict(type='raw', no_log=False),
        item=dict(type='raw', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        identify_by=dict(type='list', elements='str'),
        position=dict(type='str', choices=['start', 'end']),
        index=dict(type='int'),
        after=dict(type='raw'),
        before=dict(type='raw'),
        create=dict(type='bool', default=True),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        add_file_common_args=True,
        supports_check_mode=True,
        mutually_exclusive=[('position', 'index', 'after', 'before')],
    )
    params = module.params
    result = {}
    common = dict(document=params['document'], edit_mode=params['edit_mode'],
                  yaml_version=params['yaml_version'])

    try:
        parts = parse_key(params['key'], allow_empty=True)
        if params['state'] == 'absent' and any(params[name] is not None
                                               for name in ('position', 'index', 'after', 'before')):
            raise YamlEditError('position, index, after and before can only be used with state=present')
        if params['identify_by'] is not None and not params['identify_by']:
            raise YamlEditError('identify_by must not be empty')
    except YamlEditError as e:
        module.fail_json(msg=str(e))

    def edit(text):
        if params['state'] == 'present':
            res = ensure_list_item(text, parts, params['item'], identify_by=params['identify_by'],
                                   position=params['position'], index=params['index'], after=params['after'],
                                   before=params['before'], create=params['create'], **common)
            result['index'] = res.info['index']
        else:
            res = remove_list_items(text, parts, params['item'], identify_by=params['identify_by'], **common)
            result['removed'] = res.info['removed']
        result['action'] = res.info['action']
        return res

    run_file_edit(module, edit, result)


if __name__ == '__main__':
    main()
