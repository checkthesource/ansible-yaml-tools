# -*- coding: utf-8 -*-
# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for selectors, document selection and key renaming (1.1.0)."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import importlib.util
import os

import pytest

CORE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'plugins', 'module_utils', 'yaml_core.py')
_spec = importlib.util.spec_from_file_location('yaml_core_selectors', os.path.abspath(CORE_PATH))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)

YamlEditError = core.YamlEditError
Selector = core.Selector
edit = core.edit_yaml_text
rename = core.rename_key_text
ensure = core.ensure_list_item
remove = core.remove_list_items


VARS = """\
test:
  - name: first   # first one
    option: 1
  - name: second
    option: 3
    extra: keep
"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('key, expected', [
    ('test[name=second].option', ['test', Selector([(['name'], 'second')]), 'option']),
    ('a[ name = web ]', ['a', Selector([(['name'], 'web')])]),
    ('a[name="x]y,z"]', ['a', Selector([(['name'], 'x]y,z')])]),
    ("a[name='']", ['a', Selector([(['name'], '')])]),
    ('a[name=web,env=prod]', ['a', Selector([(['name'], 'web'), (['env'], 'prod')])]),
    ('a[metadata.name=web]', ['a', Selector([(['metadata', 'name'], 'web')])]),
    ('a["app.kubernetes.io/name"=web]', ['a', Selector([(['app.kubernetes.io/name'], 'web')])]),
    ('a[image=nginx:1.27]', ['a', Selector([(['image'], 'nginx:1.27')])]),
    ('a[name=web][0]', ['a', Selector([(['name'], 'web')]), 0]),
    ('a[0]', ['a', 0]),
    ('a["x=y"]', ['a', 'x=y']),
    (['a', {'name': 'web'}, 'b'], ['a', Selector([(['name'], 'web')]), 'b']),
    (['a', {'port': 80, 'tls': True}], ['a', Selector([(['port'], '80'), (['tls'], 'true')])]),
])
def test_parse_selectors(key, expected):
    assert core.parse_key(key) == expected


@pytest.mark.parametrize('key, message', [
    ('a[name]', 'not a list index'),
    ('a[=x]', 'empty field name'),
    ('a[name=]', 'empty value'),
    ('a[name=x', 'missing "]"'),
    ('a[name="x]', 'unterminated'),
    ('a[name=x;y]b', 'expected "." or "["'),
    ('a[name.=x]', 'empty field name'),
    (['a', {}], 'non-empty dictionary'),
    (['a', {'name': None}], 'strings, integers or booleans'),
    (['a', {'items[0]': 'x'}], 'without list indexes'),
])
def test_parse_bad_selectors(key, message):
    with pytest.raises(YamlEditError, match=message.replace('[', r'\[').replace('.', r'\.')):
        core.parse_key(key)


@pytest.mark.parametrize('key, shown', [
    ('a[name=my var,env=prod].b', 'a[name=my var,env=prod].b'),
    ('a[name="x,y"]', 'a[name="x,y"]'),
    ('a[name=" padded "]', 'a[name=" padded "]'),
    ('a["app.kubernetes.io/name"=web]', 'a["app.kubernetes.io/name"=web]'),
])
def test_format_key_shows_selectors_that_parse_back(key, shown):
    parts = core.parse_key(key)
    assert core.format_key(parts) == shown
    assert core.parse_key(shown) == parts


# ---------------------------------------------------------------------------
# Editing through selectors
# ---------------------------------------------------------------------------

def test_edit_field_of_item_selected_by_name():
    res = edit(VARS, 'test[name=second].option', value=5)
    assert res.method == 'lossless'
    assert res.text == VARS.replace('option: 3', 'option: 5')
    assert res.info['previous'] == 3


def test_selector_values_are_compared_as_text():
    text = "ports:\n  - port: 80\n    name: http\n  - port: '443'\n    name: https\n"
    assert edit(text, 'ports[port=80].name', value='web').text == text.replace('http\n', 'web\n', 1)
    assert edit(text, 'ports[port=443].name', value='tls').text == text.replace('https', 'tls')


def test_selector_with_several_and_nested_fields():
    text = """\
items:
  - meta: {name: a}
    env: dev
    v: 1
  - meta: {name: a}
    env: prod
    v: 2
"""
    res = edit(text, 'items[meta.name=a,env=prod].v', value=3)
    assert res.text == text.replace('v: 2', 'v: 3')


def test_selector_matching_several_items_fails():
    text = "l:\n  - {name: a, v: 1}\n  - {name: a, v: 2}\n"
    with pytest.raises(YamlEditError, match='2 items of l match'):
        edit(text, 'l[name=a].v', value=3)


def test_selector_matching_nothing_fails_when_setting():
    with pytest.raises(YamlEditError, match=r'no item of test matches \[name=nope\]'):
        edit(VARS, 'test[name=nope].option', value=1)


def test_selector_matching_nothing_is_fine_when_removing():
    res = edit(VARS, 'test[name=nope].option', state='absent')
    assert not res.changed and res.text == VARS


def test_remove_item_selected_by_name():
    res = edit(VARS, 'test[name=first]', state='absent')
    assert res.text == "test:\n  - name: second\n    option: 3\n    extra: keep\n"


def test_selector_on_a_mapping_fails():
    with pytest.raises(YamlEditError, match='is a mapping'):
        edit("a:\n  b: 1\n", 'a[name=x].b', value=1)


def test_selector_skips_items_that_are_not_mappings():
    text = "l:\n  - plain\n  - name: x\n    v: 1\n"
    assert edit(text, 'l[name=x].v', value=2).text == text.replace('v: 1', 'v: 2')


def test_new_key_in_selected_item():
    res = edit(VARS, 'test[name=first].comment', value='hello', after='option')
    assert res.text == VARS.replace('    option: 1\n', '    option: 1\n    comment: hello\n')


def test_key_list_form_with_selector():
    res = edit(VARS, ['test', {'name': 'second'}, 'option'], value=4)
    assert 'option: 4' in res.text


def test_yaml_list_through_a_selector():
    text = "groups:\n  - name: web\n    members:\n      - bob\n  - name: db\n    members: []\n"
    res = ensure(text, 'groups[name=web].members', 'alice')
    assert res.text == text.replace('      - bob\n', '      - bob\n      - alice\n')
    res = ensure(res.text, 'groups[name=db].members', 'carol')
    assert 'members: [carol]' in res.text


def test_yaml_list_selector_without_match():
    with pytest.raises(YamlEditError, match='no item of groups matches'):
        ensure("groups: []\n", 'groups[name=web].members', 'alice')
    assert not remove("groups: []\n", 'groups[name=web].members', 'alice').changed


def test_yaml_list_update_through_selector_keeps_the_same_item():
    text = "g:\n  - name: web\n    l:\n      - {id: 1, v: a}\n"
    res = ensure(text, 'g[name=web].l', {'id': 1, 'v': 'b', 'w': [1]}, identify_by=['id'])
    assert res.info['action'] == 'updated'
    assert 'name: web' in res.text and 'v: b' in res.text


# ---------------------------------------------------------------------------
# Documents selected by content
# ---------------------------------------------------------------------------

MANIFESTS = """\
apiVersion: v1
kind: Service
metadata:
  name: web
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 1   # scaled by the playbook
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker
spec:
  replicas: 2
"""


def test_document_selected_by_fields():
    res = edit(MANIFESTS, 'spec.replicas', value=3, document={'kind': 'Deployment', 'metadata.name': 'web'})
    assert res.text == MANIFESTS.replace('replicas: 1 ', 'replicas: 3 ')


@pytest.mark.parametrize('document, message', [
    ({'kind': 'Deployment'}, 'documents 1, 2 all match'),
    ({'kind': 'Job'}, 'no document matches kind=Job'),
    (True, 'boolean'),
    ('first', 'must be an index'),
    (7, 'document 7 does not exist'),
])
def test_bad_document_selection(document, message):
    with pytest.raises(YamlEditError, match=message):
        edit(MANIFESTS, 'spec.replicas', value=3, document=document)


def test_document_index_as_string():
    assert core.parse_document('2') == 2


def test_resolve_document():
    assert core.resolve_document(MANIFESTS, {'metadata.name': 'worker'}) == 2
    assert core.resolve_document(MANIFESTS, 1) == 1


def test_list_operations_on_selected_document():
    res = ensure(MANIFESTS, 'spec.containers', {'name': 'app'}, document={'metadata.name': 'worker'})
    assert res.info['action'] == 'created'
    assert res.text.endswith('  replicas: 2\n  containers:\n    - name: app\n')


# ---------------------------------------------------------------------------
# Renaming keys
# ---------------------------------------------------------------------------

CONFIG = """\
server:
  listen: 0.0.0.0   # all interfaces
  port: 80
"""


def test_rename_keeps_value_comment_and_position():
    res = rename(CONFIG, 'server.listen', 'bind')
    assert res.method == 'lossless'
    assert res.text == CONFIG.replace('listen:', 'bind:')
    assert res.info == {'existed': True, 'value': '0.0.0.0'}


def test_rename_is_idempotent():
    once = rename(CONFIG, 'server.listen', 'bind').text
    again = rename(once, 'server.listen', 'bind')
    assert not again.changed and again.info['existed'] is False


def test_rename_to_the_same_name():
    assert not rename(CONFIG, 'server.port', 'port').changed


def test_rename_to_an_existing_key_fails():
    with pytest.raises(YamlEditError, match='already exists'):
        rename(CONFIG, 'server.listen', 'port')


def test_rename_quotes_keys_when_needed():
    res = rename(CONFIG, 'server.port', 'yes')
    assert "  'yes': 80\n" in res.text
    res = rename("a: {x: 1, y: 2}\n", 'a.x', 'b,c')
    assert res.text == "a: {'b,c': 1, y: 2}\n"


def test_rename_block_value_and_selected_item():
    res = rename(VARS, 'test[name=second].extra', 'more')
    assert res.text == VARS.replace('extra:', 'more:')
    text = "a:\n  old:\n    x: 1   # c\n  z: 2\n"
    assert rename(text, 'a.old', 'new').text == text.replace('old:', 'new:')


def test_rename_list_item_fails():
    with pytest.raises(YamlEditError, match='only mapping keys'):
        rename(VARS, 'test[0]', 'x')


def test_rename_inherited_key_fails():
    text = "base: &b\n  x: 1\nchild:\n  <<: *b\n  y: 2\n"
    with pytest.raises(YamlEditError, match='inherited'):
        rename(text, 'child.x', 'z')


def test_rename_in_roundtrip_mode_keeps_order():
    res = rename(CONFIG, 'server.listen', 'bind', edit_mode='roundtrip')
    assert res.method == 'roundtrip'
    assert res.text.index('bind') < res.text.index('port')
