# -*- coding: utf-8 -*-
# Copyright (c) the yaml_edit contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the yaml_edit editing engine.

The tests load the module file directly, so they work both inside an
``ansible_collections`` tree and from a plain checkout.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import importlib.util
import os
import time

import pytest
from ruamel.yaml import YAML

MODULE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'plugins', 'module_utils', 'yaml_core.py')
_spec = importlib.util.spec_from_file_location('yaml_core', os.path.abspath(MODULE_PATH))
ye = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ye)

edit = ye.edit_yaml_text
YamlEditError = ye.YamlEditError


def load(text):
    return list(YAML(typ='rt').load_all(text))


CONFIG = """\
# Application settings
server:
    host: "localhost"   # where to listen
    port: 80
    debug:
    tags:
      - web
      - api

# Logging
logging:
    level: info
    format: '%(message)s'
"""


# ---------------------------------------------------------------------------
# Key parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('key, expected', [
    ('a', ['a']),
    ('a.b.c', ['a', 'b', 'c']),
    ('a[0]', ['a', 0]),
    ('a[-1].b', ['a', -1, 'b']),
    ('[0].name', [0, 'name']),
    ('a[0][1]', ['a', 0, 1]),
    ('a["b.c"].d', ['a', 'b.c', 'd']),
    ("a['x[0]']", ['a', 'x[0]']),
    (r'a\.b.c', ['a.b', 'c']),
    ('ports.80', ['ports', '80']),
    (['a', 'b.c', 0], ['a', 'b.c', 0]),
])
def test_parse_key(key, expected):
    assert ye.parse_key(key) == expected


@pytest.mark.parametrize('key', [
    '', 'a.', '.a', 'a..b', 'a[', 'a[x]', 'a[0', 'a["b]', 'a]', 'a\\', 'a[0]b', [], [''], [True], 80, None, ['a', 1.5],
])
def test_parse_key_rejects_bad_keys(key):
    with pytest.raises(YamlEditError):
        ye.parse_key(key)


# ---------------------------------------------------------------------------
# Lossless edits: only the changed bytes move
# ---------------------------------------------------------------------------

def test_replace_scalar_keeps_everything_else():
    r = edit(CONFIG, 'server.port', value=8080)
    assert r.changed and r.method == 'lossless'
    assert r.info['previous'] == 80
    assert r.text == CONFIG.replace('port: 80', 'port: 8080')


def test_replace_keeps_quote_style_and_comment():
    r = edit(CONFIG, 'server.host', value='0.0.0.0')
    assert r.text == CONFIG.replace('"localhost"', '"0.0.0.0"')
    r = edit(CONFIG, 'logging.format', value="it's %(msg)s")
    assert r.text == CONFIG.replace("'%(message)s'", "'it''s %(msg)s'")


def test_fill_empty_value():
    r = edit(CONFIG, 'server.debug', value=True)
    assert r.method == 'lossless'
    assert r.text == CONFIG.replace('    debug:\n', '    debug: true\n')


def test_replace_list_item():
    r = edit(CONFIG, 'server.tags[-1]', value='admin')
    assert r.text == CONFIG.replace('- api', '- admin')


def test_add_key_uses_existing_indentation():
    r = edit(CONFIG, 'logging.file', value='/var/log/app.log')
    assert r.method == 'lossless'
    assert r.text == CONFIG + '    file: /var/log/app.log\n'


def test_add_nested_structure_matches_file_style():
    r = edit(CONFIG, 'server.limits', value={'cpu': 2, 'paths': ['/a', {'b': 'c'}]})
    assert r.method == 'lossless'
    expected = CONFIG.replace(
        '      - api\n',
        '      - api\n'
        '    limits:\n'
        '        cpu: 2\n'
        '        paths:\n'
        '          - /a\n'
        '          - b: c\n')
    assert r.text == expected


def test_create_missing_parents():
    r = edit(CONFIG, 'logging.handlers.file.level', value='debug')
    assert r.method == 'lossless'
    assert r.text.endswith('    handlers:\n        file:\n            level: debug\n')


def test_create_under_null_value():
    r = edit(CONFIG, 'server.debug.verbose', value=1)
    assert r.method == 'lossless'
    assert '    debug:\n        verbose: 1\n    tags:' in r.text


def test_remove_key_and_its_line():
    r = edit(CONFIG, 'server.host', state='absent')
    assert r.method == 'lossless'
    assert r.text == CONFIG.replace('    host: "localhost"   # where to listen\n', '')


def test_remove_nested_block():
    r = edit(CONFIG, 'server.tags', state='absent')
    assert r.text == CONFIG.replace('    tags:\n      - web\n      - api\n', '')


def test_remove_list_item():
    r = edit(CONFIG, 'server.tags[0]', state='absent')
    assert r.text == CONFIG.replace('      - web\n', '')


def test_remove_last_entry_leaves_empty_mapping():
    text = 'a:\n  only: 1\nb: 2\n'
    r = edit(text, 'a.only', state='absent')
    assert r.text == 'a: {}\nb: 2\n'


def test_add_after_block_scalar():
    text = 'a:\n  script: |\n    echo hi\n    echo there\n\n  other: 1\nb: 2\n'
    r = edit(text, 'a.new', value='x')
    assert r.method == 'lossless'
    assert r.text == 'a:\n  script: |\n    echo hi\n    echo there\n\n  other: 1\n  new: x\nb: 2\n'


def test_trailing_comments_stay_with_next_section():
    text = 'a:\n  x: 1\n\n# about b\nb: 2\n'
    r = edit(text, 'a.z', value=2)
    assert r.text == 'a:\n  x: 1\n  z: 2\n\n# about b\nb: 2\n'


def test_new_key_that_is_a_boolean_in_yaml_1_1_is_quoted():
    # "y" is a boolean under YAML 1.1 (Ansible, PyYAML), so it must be quoted.
    r = edit('a: 1\n', 'y', value=2)
    assert r.text == "a: 1\n'y': 2\n"


def test_file_without_trailing_newline():
    r = edit('a: 1', 'b', value=2)
    assert r.text == 'a: 1\nb: 2\n'
    r = edit('a: 1', 'a', value=3)
    assert r.text == 'a: 3'


def test_crlf_line_endings_are_kept():
    text = 'a:\r\n  b: 1\r\n  c: 2\r\n'
    r = edit(text, 'a.b', value=5)
    assert r.text == 'a:\r\n  b: 5\r\n  c: 2\r\n'
    r = edit(text, 'a.d', value={'e': 1})
    assert r.text == 'a:\r\n  b: 1\r\n  c: 2\r\n  d:\r\n    e: 1\r\n'
    r = edit(text, 'a.b', state='absent')
    assert r.text == 'a:\r\n  c: 2\r\n'


def test_kubernetes_style_sequences():
    text = (
        'spec:\n'
        '  containers:\n'
        '  - name: web\n'
        '    image: nginx:1.25\n'
        '  - name: sidecar\n'
        '    image: busybox\n'
    )
    r = edit(text, 'spec.containers[0].image', value='nginx:1.27')
    assert r.text == text.replace('nginx:1.25', 'nginx:1.27')
    r = edit(text, 'spec.volumes', value=[{'name': 'data'}])
    assert r.text == text + '  volumes:\n  - name: data\n'
    r = edit(text, 'spec.containers[1]', state='absent')
    assert r.method == 'lossless'
    assert r.text == 'spec:\n  containers:\n  - name: web\n    image: nginx:1.25\n'


def test_remove_first_key_of_list_item():
    text = 'items:\n  - name: a\n    value: 1\n  - name: b\n    value: 2\n'
    r = edit(text, 'items[0].name', state='absent')
    assert r.method == 'lossless'
    assert r.text == 'items:\n  - value: 1\n  - name: b\n    value: 2\n'


def test_multi_document():
    text = '---\nkind: A\nspec:\n  replicas: 1\n---\nkind: B\nspec:\n  replicas: 1\n'
    r = edit(text, 'spec.replicas', value=3, document=1)
    assert r.text == '---\nkind: A\nspec:\n  replicas: 1\n---\nkind: B\nspec:\n  replicas: 3\n'
    with pytest.raises(YamlEditError, match='document 2 does not exist'):
        edit(text, 'spec.replicas', value=3, document=2)


def test_flow_collection_values():
    text = 'a: {x: 1, y: [1, 2]}  # inline\nb: 2\n'
    r = edit(text, 'a.y[1]', value=3)
    assert r.text == 'a: {x: 1, y: [1, 3]}  # inline\nb: 2\n'
    r = edit(text, 'a.x', value='p, q')
    assert r.method == 'lossless'
    assert load(r.text)[0]['a']['x'] == 'p, q'


def test_root_sequence():
    text = '- name: a\n  v: 1\n- name: b\n  v: 2\n'
    r = edit(text, '[1].v', value=5)
    assert r.text == '- name: a\n  v: 1\n- name: b\n  v: 5\n'


def test_unicode_is_kept():
    text = 'title: "Café"\nemoji: 🎉\n'
    r = edit(text, 'emoji', value='🚀 décollage')
    assert r.text == 'title: "Café"\nemoji: 🚀 décollage\n'


# ---------------------------------------------------------------------------
# Value safety: what is written must read back as the same value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value', [
    'yes', 'no', 'on', 'off', 'y', 'n', 'true', 'True', 'null', '~', '', ' ', '0777', '0o17', '0x1F', '1_000', '12:30',
    '1e3', '.inf', '-', '- x', '? x', 'a: b', 'a #b', '#x', '!tag', '&a', '*a', '%x', '@x', '`x', '"x"', "'x'",
    'x\ny', 'tab\there', 'back\\slash', 'trailing ', '{a}', '[a]', 'a,b', '2026-10-29', '=', '<<', '\x07bell',
    'café', '\u0085', '\u00a0x',
])
def test_strings_round_trip_under_yaml_1_1_and_1_2(value):
    for version in ('1.1', '1.2'):
        r = edit('k: old\n', 'k', value=value, yaml_version=version)
        for v in ((1, 1), (1, 2)):
            loader = YAML(typ='safe', pure=True)
            loader.version = v
            assert loader.load(r.text) == {'k': value}, (version, v, r.text)


@pytest.mark.parametrize('value', [0, -5, 10 ** 30, 1.5, -0.0, 1e20, 1e-7, float('inf'), True, False, None, [], {}])
def test_scalars_keep_their_type(value):
    r = edit('k: old\n', 'k', value=value)
    assert ye.to_plain(load(r.text)[0]['k']) == ye.to_plain(value)


def test_new_keys_are_always_strings():
    r = edit('a: 1\n', ['ports', '80'], value='http')
    assert r.text == "a: 1\nports:\n  '80': http\n"
    r = edit('a: 1\n', 'yes', value=1)
    assert r.text == "a: 1\n'yes': 1\n"


def test_existing_non_string_key_is_matched_by_text():
    text = 'ports:\n  80: http\n  443: https\n'
    r = edit(text, 'ports.80', value='web')
    assert r.text == 'ports:\n  80: web\n  443: https\n'


def test_yaml_version_controls_idempotence():
    text = 'enabled: yes\n'
    assert not edit(text, 'enabled', value=True, yaml_version='1.1').changed
    r = edit(text, 'enabled', value=True, yaml_version='1.2')
    assert r.changed and r.text == 'enabled: true\n'


def test_type_change_is_a_change():
    assert edit('a: 1\n', 'a', value='1').text == "a: '1'\n"
    assert edit('a: 1\n', 'a', value=1.0).text == 'a: 1.0\n'
    assert edit('a: 1\n', 'a', value=True).text == 'a: true\n'


# ---------------------------------------------------------------------------
# Idempotence and no-ops
# ---------------------------------------------------------------------------

def test_idempotent_set():
    r = edit(CONFIG, 'server.port', value=80)
    assert not r.changed and r.text == CONFIG and r.method is None


def test_idempotent_nested_set():
    r1 = edit(CONFIG, 'server.limits', value={'cpu': 2})
    r2 = edit(r1.text, 'server.limits', value={'cpu': 2})
    assert not r2.changed


def test_absent_on_missing_key_is_noop():
    assert not edit(CONFIG, 'server.nope', state='absent').changed
    assert not edit(CONFIG, 'nope.deeper', state='absent').changed
    assert not edit(CONFIG, 'server.tags[5]', state='absent').changed


def test_every_edit_is_stable():
    keys = ['server.port', 'server.host', 'server.debug', 'server.tags[0]', 'logging.level', 'server.new']
    for key in keys:
        r = edit(CONFIG, key, value='changed')
        assert r.method == 'lossless', key
        assert not edit(r.text, key, value='changed').changed, key


# ---------------------------------------------------------------------------
# Fallback to round-trip, and edit_mode
# ---------------------------------------------------------------------------

def test_add_to_flow_mapping_falls_back_to_roundtrip():
    text = 'a: {x: 1}\n# keep me\nb: 2\n'
    r = edit(text, 'a.y', value=2)
    assert r.method == 'roundtrip'
    assert load(r.text)[0] == {'a': {'x': 1, 'y': 2}, 'b': 2}
    assert '# keep me' in r.text


def test_lossless_mode_refuses_rewrite():
    with pytest.raises(YamlEditError, match='lossless edit is not possible'):
        edit('a: {x: 1}\n', 'a.y', value=2, edit_mode='lossless')


def test_roundtrip_mode():
    r = edit(CONFIG, 'server.port', value=8080, edit_mode='roundtrip')
    assert r.method == 'roundtrip'
    assert '# Application settings' in r.text
    assert load(r.text)[0]['server']['port'] == 8080


def test_roundtrip_quotes_ambiguous_strings():
    r = edit('a: {x: 1}\n', 'a.y', value='yes')
    assert r.method == 'roundtrip'
    loader = YAML(typ='safe', pure=True)
    loader.version = (1, 1)
    assert loader.load(r.text) == {'a': {'x': 1, 'y': 'yes'}}


def test_block_scalar_replacement_uses_roundtrip():
    text = 'script: |\n  echo hi\nother: 1\n'
    r = edit(text, 'script', value='echo bye')
    assert r.method == 'roundtrip'
    assert load(r.text)[0] == {'script': 'echo bye', 'other': 1}


def test_empty_file():
    r = edit('', 'a.b', value=1)
    assert load(r.text)[0] == {'a': {'b': 1}}
    r = edit('# just a comment\n', 'a', value=1)
    assert load(r.text)[0] == {'a': 1}


# ---------------------------------------------------------------------------
# Errors and safety
# ---------------------------------------------------------------------------

def test_create_false():
    with pytest.raises(YamlEditError, match='create=false'):
        edit(CONFIG, 'server.nope', value=1, create=False)


def test_list_items_are_never_created():
    with pytest.raises(YamlEditError, match='never created'):
        edit(CONFIG, 'server.tags[5]', value='x')


def test_wrong_container_types():
    with pytest.raises(YamlEditError, match='is a list'):
        edit(CONFIG, 'server.tags.first', value='x')
    with pytest.raises(YamlEditError, match='is a mapping'):
        edit(CONFIG, 'server[0]', value='x')
    with pytest.raises(YamlEditError, match='scalar'):
        edit(CONFIG, 'server.port.number', value=1)


def test_duplicate_keys_are_refused():
    with pytest.raises((YamlEditError, ye.YAMLError)):
        edit('a: 1\na: 2\n', 'a', value=3)


def test_aliased_values_are_refused():
    text = 'base: &b\n  x: 1\ncopy: *b\n'
    with pytest.raises(YamlEditError, match='anchor'):
        edit(text, 'base.x', value=2)
    with pytest.raises(YamlEditError, match='anchor'):
        edit(text, 'copy.x', value=2)


def test_unused_anchor_is_fine():
    r = edit('base: &b\n  x: 1\n', 'base.x', value=2)
    assert r.text == 'base: &b\n  x: 2\n'


def test_merge_keys():
    text = 'base: &b\n  x: 1\nchild:\n  <<: *b\n  y: 2\n'
    r = edit(text, 'child.x', value=5)
    assert load(r.text)[0]['child']['x'] == 5
    assert load(r.text)[0]['base']['x'] == 1
    assert not edit(text, 'child.x', value=1).changed
    with pytest.raises(YamlEditError, match='merge'):
        edit(text, 'child.x', state='absent')
    with pytest.raises(YamlEditError, match='merge'):
        edit(text, 'child.<<', value=1)


def test_alias_bomb_is_rejected_quickly():
    lines = ['a0: &a0 [x, x, x, x, x, x, x, x, x, x]']
    for i in range(1, 12):
        prev = '*a%d' % (i - 1)
        lines.append('a%d: &a%d [%s]' % (i, i, ', '.join([prev] * 10)))
    lines.append('target: 1')
    text = '\n'.join(lines) + '\n'
    start = time.time()
    with pytest.raises(YamlEditError, match='too large'):
        edit(text, 'target', value=2)
    assert time.time() - start < 10


def test_recursive_alias():
    text = 'a: &a [1, *a]\nb: 1\n'
    assert edit(text, 'b', value=2).text == 'a: &a [1, *a]\nb: 2\n'
    with pytest.raises(YamlEditError, match='anchor'):
        edit(text, 'a[0]', value=2)


def test_tags_are_kept_on_untouched_values():
    text = 'secret: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n  6162\nother: 1\n'
    r = edit(text, 'other', value=2)
    assert r.text == text.replace('other: 1', 'other: 2')


def test_rejects_unsupported_values():
    with pytest.raises(YamlEditError):
        edit('a: 1\n', 'a', value=object())
    with pytest.raises(YamlEditError):
        edit('a: 1\n', 'a', value={1: 'x'})


def test_parse_errors_do_not_leak_file_content():
    try:
        edit('password: s3cr3t\nbad: [unclosed\n', 'a', value=1)
    except ye.YAMLError as e:
        message = ye.describe_yaml_error(e)
        assert 's3cr3t' not in message
        assert 'line' in message
    else:
        pytest.fail('expected a parse error')


def test_values_cannot_inject_yaml():
    r = edit('a: 1\nb: 2\n', 'a', value='x\nb: 666')
    assert load(r.text)[0] == {'a': 'x\nb: 666', 'b': 2}
    r = edit('a: 1\n', ['evil: 1\nc'], value='x')
    assert load(r.text)[0] == {'a': 1, 'evil: 1\nc': 'x'}


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def test_read_utf8_with_bom(tmp_path):
    f = tmp_path / 'bom.yaml'
    f.write_bytes(b'\xef\xbb\xbfa: 1\n')
    text, bom = ye.read_yaml_file(str(f))
    assert text == 'a: 1\n' and bom


def test_read_rejects_other_encodings(tmp_path):
    f = tmp_path / 'utf16.yaml'
    f.write_bytes('a: 1\n'.encode('utf-16'))
    with pytest.raises(YamlEditError, match='UTF-16'):
        ye.read_yaml_file(str(f))
    f.write_bytes(b'a: caf\xe9\n')
    with pytest.raises(YamlEditError, match='UTF-8'):
        ye.read_yaml_file(str(f))


# ---------------------------------------------------------------------------
# value_type conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value, value_type, expected', [
    ('8080', 'int', 8080),
    (' 42 ', 'int', 42),
    (3.0, 'int', 3),
    ('1.5', 'float', 1.5),
    (2, 'float', 2.0),
    ('yes', 'bool', True),
    ('False', 'bool', False),
    (8080, 'str', '8080'),
    (True, 'str', 'true'),
    (None, 'null', None),
    ({'a': [1]}, 'raw', {'a': [1]}),
])
def test_convert_value(value, value_type, expected):
    assert ye.convert_value(value, value_type) == expected


@pytest.mark.parametrize('value, value_type', [
    ('abc', 'int'), (1.5, 'int'), (True, 'int'), ('maybe', 'bool'), ('x', 'float'), ('x', 'null'), ([1], 'str'),
])
def test_convert_value_errors(value, value_type):
    with pytest.raises(YamlEditError):
        ye.convert_value(value, value_type)
