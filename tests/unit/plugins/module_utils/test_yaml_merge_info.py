# -*- coding: utf-8 -*-
# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for merging dictionaries and reading values (1.1.0)."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import importlib.util
import os

import pytest
from ruamel.yaml import YAML

CORE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'plugins', 'module_utils', 'yaml_core.py')
_spec = importlib.util.spec_from_file_location('yaml_core_merge', os.path.abspath(CORE_PATH))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)

YamlEditError = core.YamlEditError
merge = core.merge_yaml_text
read = core.read_yaml_value


def load(text):
    return YAML(typ='safe', pure=True).load(text)


CONFIG = """\
# Application settings
server:
  port: 80          # public port
  tls:
    enabled: false
  hosts:
    - a.example.com
logging: {level: WARN}
"""


# ---------------------------------------------------------------------------
# yaml_merge
# ---------------------------------------------------------------------------

def test_merge_only_writes_the_differences():
    res = merge(CONFIG, 'server', {'port': 8080, 'tls': {'enabled': True, 'cert': '/etc/x.pem'}, 'workers': 4})
    assert res.method == 'lossless'
    assert res.text == """\
# Application settings
server:
  port: 8080          # public port
  tls:
    enabled: true
    cert: /etc/x.pem
  hosts:
    - a.example.com
  workers: 4
logging: {level: WARN}
"""
    assert res.info['changes'] == [['server', 'port'], ['server', 'tls', 'enabled'], ['server', 'tls', 'cert'],
                                   ['server', 'workers']]


def test_merge_is_idempotent():
    value = {'server': {'port': 8080, 'hosts': ['b.example.com']}, 'logging': {'level': 'INFO'}}
    once = merge(CONFIG, None, value, list_merge='append')
    again = merge(once.text, None, value, list_merge='append')
    assert once.changed and not again.changed
    assert again.text == once.text
    assert again.info['changes'] == []


@pytest.mark.parametrize('list_merge, expected', [
    ('replace', ['b', 'c']),
    ('keep', ['a.example.com']),
    ('append', ['a.example.com', 'b', 'c']),
    ('prepend', ['b', 'c', 'a.example.com']),
])
def test_list_merge_strategies(list_merge, expected):
    res = merge(CONFIG, 'server', {'hosts': ['b', 'c', 'b']} if list_merge != 'replace' else {'hosts': ['b', 'c']},
                list_merge=list_merge)
    assert load(res.text)['server']['hosts'] == expected
    assert '# public port' in res.text


def test_append_skips_items_already_present():
    res = merge(CONFIG, 'server', {'hosts': ['a.example.com', 'z']}, list_merge='append')
    assert load(res.text)['server']['hosts'] == ['a.example.com', 'z']


def test_merge_creates_missing_mapping():
    res = merge(CONFIG, 'cache.redis', {'host': 'localhost'})
    assert load(res.text)['cache'] == {'redis': {'host': 'localhost'}}
    assert res.text.startswith(CONFIG)


def test_merge_create_false():
    with pytest.raises(YamlEditError, match='create=false'):
        merge(CONFIG, 'cache', {'a': 1}, create=False)


def test_merge_replaces_scalars_and_lists_by_dictionaries():
    res = merge("a: 1\nb: [1]\n", None, {'a': {'x': 1}, 'b': {'y': 2}})
    assert load(res.text) == {'a': {'x': 1}, 'b': {'y': 2}}


def test_merge_into_flow_mapping_falls_back_to_roundtrip():
    res = merge(CONFIG, 'logging', {'format': 'json'})
    assert load(res.text)['logging'] == {'level': 'WARN', 'format': 'json'}
    with pytest.raises(YamlEditError, match='lossless'):
        merge(CONFIG, 'logging', {'format': 'json'}, edit_mode='lossless')


def test_merge_into_list_item_selected_by_name():
    text = "containers:\n  - name: web\n    image: nginx\n  - name: db\n    image: postgres\n"
    res = merge(text, 'containers[name=db]', {'resources': {'limits': {'cpu': '1'}}})
    assert res.text == text + "    resources:\n      limits:\n        cpu: '1'\n"


def test_merge_on_selected_document():
    text = "kind: A\nv: 1\n---\nkind: B\nv: 1\n"
    res = merge(text, None, {'v': 2}, document={'kind': 'B'})
    assert res.text == "kind: A\nv: 1\n---\nkind: B\nv: 2\n"


def test_merge_into_empty_document_fails():
    with pytest.raises(YamlEditError, match='empty'):
        merge("", None, {'a': 1})


def test_merge_needs_a_dictionary():
    with pytest.raises(YamlEditError, match='dictionary'):
        merge(CONFIG, None, ['a'])
    with pytest.raises(YamlEditError, match='list_merge'):
        merge(CONFIG, None, {}, list_merge='union')


def test_merge_through_an_alias_is_refused():
    text = "base: &b\n  x: 1\nother: *b\n"
    with pytest.raises(YamlEditError, match='anchor'):
        merge(text, 'other', {'x': 2})


# ---------------------------------------------------------------------------
# yaml_info
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('key, exists, value, kind', [
    ('server.port', True, 80, 'int'),
    ('server.tls', True, {'enabled': False}, 'dict'),
    ('server.hosts', True, ['a.example.com'], 'list'),
    ('server.hosts[-1]', True, 'a.example.com', 'str'),
    ('logging.level', True, 'WARN', 'str'),
    ('server.missing', False, None, None),
    ('missing.deeper.key', False, None, None),
    ('server.hosts[5]', False, None, None),
])
def test_read_values(key, exists, value, kind):
    res = read(CONFIG, key)
    assert (res['exists'], res['value'], res['type']) == (exists, value, kind)


def test_read_whole_document_and_counts():
    res = read("a: 1\n---\nb: null\n", None, document=1)
    assert res == {'exists': True, 'value': {'b': None}, 'type': 'dict', 'document': 1, 'documents': 2}
    assert read("a: 1\n---\nb: null\n", 'b', document=1)['type'] == 'null'


def test_read_selector_and_document_selector():
    text = "kind: A\nl:\n  - {name: x, v: 1.5}\n---\nkind: B\nl: []\n"
    res = read(text, 'l[name=x].v', document={'kind': 'A'})
    assert (res['exists'], res['value'], res['type'], res['document']) == (True, 1.5, 'float', 0)
    assert read(text, 'l[name=x].v', document={'kind': 'B'})['exists'] is False


def test_read_through_aliases_and_merge_keys():
    text = "base: &b\n  x: 1\n  when: 2026-10-30\nchild:\n  <<: *b\n  y: true\nother: *b\n"
    assert read(text, 'other.x')['value'] == 1
    assert read(text, 'child.x')['value'] == 1
    assert read(text, 'child.y')['type'] == 'bool'
    assert read(text, 'child.when', yaml_version='1.1')['type'] == 'timestamp'


def test_read_yaml_version_matters():
    assert read("a: yes\n", 'a')['value'] == 'yes'
    assert read("a: yes\n", 'a', yaml_version='1.1')['value'] is True


def test_read_errors():
    with pytest.raises(YamlEditError, match='scalar'):
        read(CONFIG, 'server.port.x')
    with pytest.raises(YamlEditError, match='2 items'):
        read("l: [{n: a}, {n: a}]\n", 'l[n=a]')


# ---------------------------------------------------------------------------
# infer_types (templated numbers arrive as strings before ansible-core 2.19)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value, expected', [
    ('42', 42), ('0', 0), ('-7', -7), ('true', True), ('False', False), ('TRUE', True),
    ('0755', '0755'), ('1.10', '1.10'), ('1e3', '1e3'), ('yes', 'yes'), ('+5', '+5'), (' 42', ' 42'),
    ('', ''), ('None', 'None'), (42, 42), (None, None),
    ({'a': '1', '2': ['3', 'x']}, {'a': 1, '2': [3, 'x']}),
])
def test_infer_types(value, expected):
    assert core.infer_types(value) == expected


ITEMS = """\
entries:
  - name: first
    group: g1
    number: 4001
  - name: second
    group: g1
    number: 97
"""


def test_templated_numbers_are_idempotent_with_infer_types():
    templated = {'name': 'first', 'group': 'g1', 'number': '4001'}
    res = core.ensure_list_item(ITEMS, 'entries', core.infer_types(templated))
    assert not res.changed and res.info['action'] == 'unchanged'
    new = core.infer_types({'name': 'third', 'group': 'g2', 'number': '1104'})
    res = core.ensure_list_item(ITEMS, 'entries', new)
    assert res.text.endswith("  - name: third\n    group: g2\n    number: 1104\n")
    assert not core.ensure_list_item(res.text, 'entries', new).changed


def test_without_infer_types_templated_numbers_stay_strings():
    res = core.ensure_list_item(ITEMS, 'entries', {'name': 'third', 'group': 'g2', 'number': '1104'})
    assert res.text.endswith("    number: '1104'\n")
