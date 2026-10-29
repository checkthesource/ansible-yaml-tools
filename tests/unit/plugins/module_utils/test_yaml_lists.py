# -*- coding: utf-8 -*-
# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for list operations and key positioning."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import importlib.util
import os

import pytest
from ruamel.yaml import YAML

CORE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'plugins', 'module_utils', 'yaml_core.py')
_spec = importlib.util.spec_from_file_location('yaml_core_lists', os.path.abspath(CORE_PATH))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)

YamlEditError = core.YamlEditError
ensure = core.ensure_list_item
remove = core.remove_list_items
edit = core.edit_yaml_text


def load(text):
    return list(YAML(typ='rt').load_all(text))


CONFIG = """\
# Servers
server:
    tags:
      - web    # front
      - api
    port: 80
"""

K8S = """\
spec:
  containers:
  - name: web
    image: nginx:1.25
  - name: sidecar
    image: busybox
"""


# ---------------------------------------------------------------------------
# Adding items
# ---------------------------------------------------------------------------

def test_append_at_end():
    r = ensure(CONFIG, 'server.tags', 'admin')
    assert r.method == 'lossless' and r.info == {'action': 'added', 'index': 2}
    assert r.text == CONFIG.replace('      - api\n', '      - api\n      - admin\n')


def test_append_is_idempotent():
    r = ensure(CONFIG, 'server.tags', 'admin')
    again = ensure(r.text, 'server.tags', 'admin')
    assert not again.changed and again.info == {'action': 'unchanged', 'index': 2}
    assert not ensure(CONFIG, 'server.tags', 'web').changed


def test_insert_at_start_keeps_comments():
    r = ensure(CONFIG, 'server.tags', 'admin', position='start')
    assert r.text == CONFIG.replace('      - web    # front\n', '      - admin\n      - web    # front\n')


def test_insert_at_index():
    r = ensure(CONFIG, 'server.tags', 'admin', index=1)
    assert load(r.text)[0]['server']['tags'] == ['web', 'admin', 'api']
    assert r.method == 'lossless'
    with pytest.raises(YamlEditError, match='out of range'):
        ensure(CONFIG, 'server.tags', 'admin', index=5)


def test_insert_after_and_before():
    r = ensure(CONFIG, 'server.tags', 'admin', after='web')
    assert load(r.text)[0]['server']['tags'] == ['web', 'admin', 'api']
    r = ensure(CONFIG, 'server.tags', 'admin', before='web')
    assert load(r.text)[0]['server']['tags'] == ['admin', 'web', 'api']
    with pytest.raises(YamlEditError, match='no item'):
        ensure(CONFIG, 'server.tags', 'admin', after='nope')


def test_position_options_are_exclusive():
    with pytest.raises(YamlEditError, match='mutually exclusive'):
        ensure(CONFIG, 'server.tags', 'x', index=0, after='web')


def test_add_dictionary_kubernetes_style():
    item = {'name': 'metrics', 'image': 'exporter:1', 'ports': [{'containerPort': 9102}]}
    r = ensure(K8S, 'spec.containers', item, identify_by=['name'], after={'name': 'web'})
    assert r.method == 'lossless' and r.info['index'] == 1
    assert r.text == K8S.replace(
        '  - name: sidecar\n',
        '  - name: metrics\n'
        '    image: exporter:1\n'
        '    ports:\n'
        '    - containerPort: 9102\n'
        '  - name: sidecar\n')


def test_update_with_identify_by():
    r = ensure(K8S, 'spec.containers', {'name': 'web', 'image': 'nginx:1.27'}, identify_by=['name'])
    assert r.info == {'action': 'updated', 'index': 0}
    assert r.method == 'lossless'
    assert r.text == K8S.replace('nginx:1.25', 'nginx:1.27')
    again = ensure(r.text, 'spec.containers', {'name': 'web', 'image': 'nginx:1.27'}, identify_by=['name'])
    assert not again.changed


def test_update_scalar_item_in_place():
    text = 'hosts:\n  - a.example.com  # primary\n  - b.example.com\n'
    r = ensure(text, 'hosts', 'a.example.com', identify_by=None)
    assert not r.changed


def test_identify_by_needs_a_dictionary_with_the_fields():
    with pytest.raises(YamlEditError, match='dictionary'):
        ensure(K8S, 'spec.containers', 'web', identify_by=['name'])
    with pytest.raises(YamlEditError, match="'name'"):
        ensure(K8S, 'spec.containers', {'image': 'x'}, identify_by=['name'])


def test_identify_by_must_be_unique():
    text = 'l:\n  - {n: 1, v: a}\n  - {n: 1, v: b}\n'
    with pytest.raises(YamlEditError, match='unique'):
        ensure(text, 'l', {'n': 1, 'v': 'c'}, identify_by=['n'])


def test_create_missing_list():
    r = ensure(CONFIG, 'server.allowed', '10.0.0.1')
    assert r.info['action'] == 'created'
    assert load(r.text)[0]['server']['allowed'] == ['10.0.0.1']
    with pytest.raises(YamlEditError, match='create=false'):
        ensure(CONFIG, 'server.allowed', '10.0.0.1', create=False)


def test_fill_null_list():
    text = 'tags:\nother: 1\n'
    r = ensure(text, 'tags', 'x')
    assert r.text == 'tags:\n  - x\nother: 1\n'


def test_not_a_list():
    with pytest.raises(YamlEditError, match='not a list'):
        ensure(CONFIG, 'server.port', 'x')


def test_flow_lists():
    text = 'a: [1, 2]  # inline\nb: []\n'
    r = ensure(text, 'a', 3)
    assert r.text == 'a: [1, 2, 3]  # inline\nb: []\n'
    r = ensure(text, 'a', 0, position='start')
    assert r.text == 'a: [0, 1, 2]  # inline\nb: []\n'
    r = ensure(text, 'b', 'x, y')
    assert r.method == 'lossless'
    assert load(r.text)[0]['b'] == ['x, y']
    r = ensure(text, 'a', {'k': 1})
    assert r.method == 'roundtrip'
    assert load(r.text)[0]['a'] == [1, 2, {'k': 1}]


def test_root_list():
    tasks = '- name: first\n  debug: msg=1\n\n- name: second\n  debug: msg=2\n'
    r = ensure(tasks, None, {'name': 'zero', 'debug': 'msg=0'}, index=0)
    assert r.text == '- name: zero\n  debug: msg=0\n- name: first\n  debug: msg=1\n\n- name: second\n  debug: msg=2\n'
    r = ensure(tasks, [], {'name': 'third'})
    assert r.text == tasks + '- name: third\n'


def test_string_items_are_quoted_when_needed():
    r = ensure(CONFIG, 'server.tags', 'yes')
    assert "      - 'yes'\n" in r.text


def test_crlf():
    text = 'l:\r\n  - a\r\n'
    r = ensure(text, 'l', 'b')
    assert r.text == 'l:\r\n  - a\r\n  - b\r\n'


def test_aliased_list_is_refused():
    text = 'a: &l [1]\nb: *l\n'
    with pytest.raises(YamlEditError, match='anchor'):
        ensure(text, 'a', 2)


# ---------------------------------------------------------------------------
# Removing items
# ---------------------------------------------------------------------------

def test_remove_by_value():
    r = remove(CONFIG, 'server.tags', 'api')
    assert r.info == {'action': 'removed', 'removed': 1}
    assert r.text == CONFIG.replace('      - api\n', '')


def test_remove_all_matches():
    text = 'l:\n  - a\n  - b\n  - a\n'
    r = remove(text, 'l', 'a')
    assert r.info['removed'] == 2
    assert r.text == 'l:\n  - b\n'


def test_remove_by_identify_by():
    r = remove(K8S, 'spec.containers', {'name': 'sidecar'}, identify_by=['name'])
    assert r.method == 'lossless'
    assert r.text == 'spec:\n  containers:\n  - name: web\n    image: nginx:1.25\n'


def test_remove_needs_exact_match_without_identify_by():
    assert not remove(K8S, 'spec.containers', {'name': 'sidecar'}).changed


def test_remove_missing_is_noop():
    assert not remove(CONFIG, 'server.tags', 'nope').changed
    assert not remove(CONFIG, 'server.missing', 'nope').changed


def test_items_that_contain_aliases():
    # An alias node carries the position of its anchor, so the lossless edit must
    # not use it to find where an item ends (regression found on a real file).
    text = 'defs:\n  - &img >-\n    {{ x }}\nlayers:\n  - background:\n      image: *img\n  - other: 1\nend: 1\n'
    r = remove(text, 'layers', {'other': 1})
    assert load(r.text)[0]['layers'] == [{'background': {'image': '{{ x }}'}}]
    r = ensure(text, 'layers', 'new')
    assert load(r.text)[0]['layers'][-1] == 'new'
    assert load(r.text)[0]['end'] == 1
    r = remove(text, 'layers', {'background': {'image': '{{ x }}'}})
    assert load(r.text)[0]['layers'] == [{'other': 1}]


def test_remove_last_item():
    r = remove('l:\n  - a\nb: 1\n', 'l', 'a')
    assert r.text == 'l: []\nb: 1\n'


# ---------------------------------------------------------------------------
# Key positioning (yaml_edit after / before)
# ---------------------------------------------------------------------------

POSITIONS = """\
server:
  host: localhost   # comment
  port: 80
  tags:
    - a
logging: {}
"""


def test_new_key_after_sibling():
    r = edit(POSITIONS, 'server.timeout', value=30, after='port')
    assert r.method == 'lossless'
    assert r.text == POSITIONS.replace('  port: 80\n', '  port: 80\n  timeout: 30\n')


def test_new_key_after_a_block():
    r = edit(POSITIONS, 'server.timeout', value=30, after='tags')
    assert r.text == POSITIONS.replace('    - a\n', '    - a\n  timeout: 30\n')


def test_new_key_before_sibling():
    r = edit(POSITIONS, 'server.scheme', value='https', before='host')
    assert r.text == POSITIONS.replace('server:\n', 'server:\n  scheme: https\n')
    assert list(load(r.text)[0]['server'].keys()) == ['scheme', 'host', 'port', 'tags']


def test_new_key_position_in_flow_mapping_uses_roundtrip():
    r = edit('a: {x: 1, z: 3}\n', 'a.y', value=2, after='x')
    assert r.method == 'roundtrip'
    assert list(load(r.text)[0]['a'].keys()) == ['x', 'y', 'z']


def test_position_errors():
    with pytest.raises(YamlEditError, match='does not exist'):
        edit(POSITIONS, 'server.timeout', value=30, after='nope')
    with pytest.raises(YamlEditError, match='parent'):
        edit(POSITIONS, 'new.timeout', value=30, after='port')
    with pytest.raises(YamlEditError, match='mutually exclusive'):
        edit(POSITIONS, 'server.timeout', value=30, after='port', before='host')


def test_existing_key_is_not_moved():
    r = edit(POSITIONS, 'server.host', value='example.com', after='tags')
    assert list(load(r.text)[0]['server'].keys()) == ['host', 'port', 'tags']


# ---------------------------------------------------------------------------
# Several edits chained on the same text (yaml_edit edits)
# ---------------------------------------------------------------------------

def test_chained_edits_stay_lossless():
    text = POSITIONS
    for key, value in (('server.port', 8080), ('server.timeout', 30), ('logging.level', 'info')):
        text = edit(text, key, value=value).text
    data = load(text)[0]
    assert data['server']['port'] == 8080 and data['server']['timeout'] == 30
    assert data['logging'] == {'level': 'info'}
    assert '  host: localhost   # comment\n' in text
