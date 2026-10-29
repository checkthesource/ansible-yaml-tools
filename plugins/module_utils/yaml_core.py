# -*- coding: utf-8 -*-

# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared engine for the yaml_tools modules.

Every edit follows the same steps:

1. Parse the text, keeping the exact position of every node.
2. Compute the data the file must contain after the edit ("expected").
3. Try a lossless edit: change only the text of the target.
4. If that is not possible, and the caller allows it, rewrite the document
   with ruamel.yaml (round-trip).
5. Parse the result again and compare it with the expected data. Any
   difference is an error and nothing is written.

The engine works on strings and never touches the filesystem, except for the
file helpers at the end of this file.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import copy
import io
import math
import os
import re
import shlex
import tempfile
import traceback
import warnings

from ansible.module_utils.common.text.converters import to_bytes, to_native
from ansible.module_utils.parsing.convert_bool import boolean

RUAMEL_IMPORT_ERROR = None
try:
    from ruamel.yaml import YAML
    from ruamel.yaml.error import MarkedYAMLError, YAMLError
    from ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode
    from ruamel.yaml.comments import CommentedMap, CommentedSeq, TaggedScalar
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString
    HAS_RUAMEL = True
except ImportError:
    HAS_RUAMEL = False
    RUAMEL_IMPORT_ERROR = traceback.format_exc()

    class YAMLError(Exception):  # pylint: disable=function-redefined
        """Placeholder so that ``except YAMLError`` works without ruamel.yaml."""


# Hard limit on the size of the data, counted after alias expansion. It stops
# "billion laughs" style alias bombs from exhausting memory or CPU.
MAX_EXPANDED_NODES = 1000000

# Characters that cannot start a plain (unquoted) scalar, or that change its
# meaning inside a flow collection.
_PLAIN_FORBIDDEN_START = set('-?:,[]{}#&*!|>\'"%@`')
_FLOW_INDICATORS = set(',[]{}')

YAML_VERSIONS = {'1.1': (1, 1), '1.2': (1, 2)}


class YamlEditError(Exception):
    """An error that is reported to the user as is."""


class LosslessUnsupported(Exception):
    """The requested change cannot be made without rewriting the file."""


# ---------------------------------------------------------------------------
# Common module options
# ---------------------------------------------------------------------------

def common_argument_spec():
    """Options shared by every module of the collection (see the ``common`` doc fragment)."""
    return dict(
        path=dict(type='path', required=True, aliases=['dest']),
        document=dict(type='int', default=0),
        edit_mode=dict(type='str', default='auto', choices=['auto', 'lossless', 'roundtrip']),
        yaml_version=dict(type='str', default='1.2', choices=['1.1', '1.2']),
        backup=dict(type='bool', default=False),
        validate=dict(type='str'),
    )


# ---------------------------------------------------------------------------
# Key path parsing
# ---------------------------------------------------------------------------

def parse_key(key, allow_empty=False):
    """Turn a key path into a list of str (mapping keys) and int (list indexes)."""
    if key is None and allow_empty:
        return []
    if isinstance(key, (list, tuple)):
        if not key and not allow_empty:
            raise YamlEditError('key must not be empty')
        parts = []
        for item in key:
            if isinstance(item, bool):
                raise YamlEditError('key items must be strings or integers, got a boolean: %r' % (item,))
            if isinstance(item, int):
                parts.append(int(item))
            elif isinstance(item, str):
                if item == '':
                    raise YamlEditError('key items must not be empty strings')
                parts.append(str(item))
            else:
                raise YamlEditError('key items must be strings or integers, got %s' % type(item).__name__)
        return parts

    if not isinstance(key, str):
        raise YamlEditError(
            'key must be a string or a list, got %s. Quote it if it is a number, for example key: "80"'
            % type(key).__name__)
    key = str(key)
    if key == '':
        if allow_empty:
            return []
        raise YamlEditError('key must not be empty')

    parts = []
    i = 0
    n = len(key)
    expect_segment = True  # a bare segment may start here
    while i < n:
        c = key[i]
        if c == '[':
            end, part = _parse_bracket(key, i)
            parts.append(part)
            i = end
            expect_segment = False
            if i < n:
                if key[i] == '.':
                    i += 1
                    expect_segment = True
                    if i >= n:
                        raise YamlEditError('invalid key %r: it ends with a dot' % key)
                elif key[i] != '[':
                    raise YamlEditError('invalid key %r: expected "." or "[" at position %d' % (key, i))
        elif expect_segment:
            buf = []
            while i < n and key[i] not in '.[':
                if key[i] == '\\':
                    if i + 1 >= n:
                        raise YamlEditError('invalid key %r: it ends with a backslash' % key)
                    buf.append(key[i + 1])
                    i += 2
                    continue
                if key[i] == ']':
                    raise YamlEditError('invalid key %r: unexpected "]" at position %d' % (key, i))
                buf.append(key[i])
                i += 1
            if not buf:
                raise YamlEditError('invalid key %r: empty key at position %d' % (key, i))
            parts.append(''.join(buf))
            expect_segment = False
            if i < n and key[i] == '.':
                i += 1
                expect_segment = True
                if i >= n:
                    raise YamlEditError('invalid key %r: it ends with a dot' % key)
        else:
            raise YamlEditError('invalid key %r at position %d' % (key, i))
    return parts


def _parse_bracket(key, start):
    """Parse ``[0]``, ``[-1]``, ``["a.b"]`` or ``['a.b']`` starting at ``key[start] == '['``."""
    i = start + 1
    n = len(key)
    if i < n and key[i] in '"\'':
        quote = key[i]
        i += 1
        buf = []
        while i < n and key[i] != quote:
            if key[i] == '\\' and i + 1 < n:
                buf.append(key[i + 1])
                i += 2
                continue
            buf.append(key[i])
            i += 1
        if i >= n or i + 1 >= n or key[i + 1] != ']':
            raise YamlEditError('invalid key %r: unterminated quoted key at position %d' % (key, start))
        if not buf:
            raise YamlEditError('invalid key %r: empty quoted key at position %d' % (key, start))
        return i + 2, ''.join(buf)
    end = key.find(']', i)
    if end == -1:
        raise YamlEditError('invalid key %r: missing "]" after position %d' % (key, start))
    text = key[i:end].strip()
    if not re.match(r'^-?[0-9]+$', text):
        raise YamlEditError(
            'invalid key %r: %r is not a list index. Quote mapping keys in brackets, for example ["%s"]'
            % (key, key[start:end + 1], text))
    return end + 1, int(text)


def format_key(parts):
    if not parts:
        return 'the document root'
    out = []
    for p in parts:
        if isinstance(p, int):
            out.append('[%d]' % p)
        elif re.match(r'^[^.\[\]\\"\']+$', p):
            out.append(('.' if out else '') + p)
        else:
            out.append('[%s]' % _double_quoted(p))
    return ''.join(out)


def _describe(parts, i):
    if i == 0:
        return 'the document root'
    return 'the value at %s' % format_key(parts[:i])


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

_LOADER_CACHE = {}


def _quiet_load(yaml, stream):
    """Load without the warnings ruamel.yaml prints for YAML 1.1 quirks (they would end up in module output)."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return yaml.load(stream)


def _safe_loader(version):
    loader = _LOADER_CACHE.get(version)
    if loader is None:
        loader = YAML(typ='safe', pure=True)
        loader.version = version
        _LOADER_CACHE[version] = loader
    return loader


def _rt(version):
    yaml = YAML(typ='rt')
    yaml.version = version
    return yaml


def _rt_dumper(indent):
    yaml = YAML(typ='rt')
    yaml.preserve_quotes = True
    yaml.width = 4096
    mapping, offset = indent
    yaml.indent(mapping=mapping, sequence=offset + 2, offset=offset)
    return yaml


def compose_documents(text, version):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return list(_rt(version).compose_all(io.StringIO(text)))


def load_documents(text, version):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return list(_rt(version).load_all(text))


def _is_empty_null(node):
    """True for an implicit null such as ``key:`` with nothing after the colon."""
    return (isinstance(node, ScalarNode) and node.value == '' and node.style is None
            and node.tag == 'tag:yaml.org,2002:null')


def _is_null(node):
    return node is None or (isinstance(node, ScalarNode) and node.tag == 'tag:yaml.org,2002:null')


def find_shared_nodes(root):
    """Return the ids of nodes used more than once (anchors referenced by aliases)."""
    seen = set()
    shared = set()
    stack = [root] if root is not None else []
    while stack:
        node = stack.pop()
        if id(node) in seen:
            shared.add(id(node))
            continue
        seen.add(id(node))
        if isinstance(node, MappingNode):
            for k, v in node.value:
                stack.append(k)
                stack.append(v)
        elif isinstance(node, SequenceNode):
            stack.extend(node.value)
    return shared


# ---------------------------------------------------------------------------
# Plain data, used to compare documents before and after an edit
# ---------------------------------------------------------------------------

class _Budget(object):
    def __init__(self, limit=MAX_EXPANDED_NODES):
        self.left = limit

    def spend(self, amount):
        self.left -= amount
        if self.left < 0:
            raise YamlEditError(
                'the YAML data is too large once aliases are expanded (more than %d nodes); '
                'this can be caused by an alias bomb' % MAX_EXPANDED_NODES)


def to_plain(obj, budget=None):
    """Convert loaded YAML (or a module value) into comparable plain Python data.

    Scalars are tagged with their type so that, for example, ``1`` and ``true``
    or ``1`` and ``1.0`` never compare equal. Shared sub-structures (aliases)
    are converted once, recursive structures are rejected, and the expanded size
    is bounded by ``budget``.
    """
    if budget is None:
        budget = _Budget()
    memo = {}
    in_progress = set()

    def conv(o):
        oid = id(o)
        if oid in memo:
            result, size = memo[oid]
            budget.spend(size)
            return result, size
        if isinstance(o, dict):
            if oid in in_progress:
                raise YamlEditError('recursive YAML aliases are not supported')
            in_progress.add(oid)
            out = {}
            size = 1
            for k, v in o.items():
                pk, sk = conv(k)
                pv, sv = conv(v)
                out[_hashable(pk)] = pv
                size += sk + sv
            in_progress.discard(oid)
            budget.spend(1)
            memo[oid] = (out, size)
            return out, size
        if isinstance(o, (list, tuple)) and not isinstance(o, str):
            if oid in in_progress:
                raise YamlEditError('recursive YAML aliases are not supported')
            in_progress.add(oid)
            out = []
            size = 1
            for v in o:
                pv, sv = conv(v)
                out.append(pv)
                size += sv
            in_progress.discard(oid)
            budget.spend(1)
            memo[oid] = (out, size)
            return out, size
        if isinstance(o, (set, frozenset)):
            budget.spend(len(o) + 1)
            return ('set', frozenset(_hashable(conv(v)[0]) for v in o)), len(o) + 1
        budget.spend(1)
        return _plain_scalar(o), 1

    return conv(obj)[0]


def _plain_scalar(o):
    if o is None:
        return None
    if isinstance(o, bool):
        return ('bool', bool(o))
    if isinstance(o, int):
        return ('int', int(o))
    if isinstance(o, float):
        f = float(o)
        if math.isnan(f):
            return ('float', 'nan')
        return ('float', f)
    if isinstance(o, str):
        return str(o)
    if isinstance(o, bytes):
        return ('bytes', bytes(o))
    if HAS_RUAMEL and isinstance(o, TaggedScalar):
        return ('tagged', str(o.tag), str(o.value))
    if hasattr(o, 'isoformat'):
        return ('time', o.isoformat())
    return ('other', type(o).__name__, repr(o))


def _hashable(p):
    if isinstance(p, dict):
        return ('map', tuple(sorted(((repr(k), _hashable(v)) for k, v in p.items()))))
    if isinstance(p, list):
        return ('seq', tuple(_hashable(v) for v in p))
    return p


def plain_to_json(p):
    """Turn plain data back into JSON-friendly values for module results."""
    if isinstance(p, dict):
        return dict((str(plain_to_json(k)), plain_to_json(v)) for k, v in p.items())
    if isinstance(p, list):
        return [plain_to_json(v) for v in p]
    if isinstance(p, tuple):
        kind = p[0]
        if kind in ('bool', 'int'):
            return p[1]
        if kind == 'float':
            return float('nan') if p[1] == 'nan' else p[1]
        if kind == 'bytes':
            return to_native(p[1], errors='surrogate_or_replace')
        if kind == 'tagged':
            return p[2]
        if kind == 'time':
            return p[1]
        if kind == 'set':
            return sorted((plain_to_json(v) for v in p[1]), key=repr)
        if kind in ('map', 'seq'):
            return repr(p)
        return p[-1]
    return p


def plain_matches(element, pattern, partial):
    """Whether plain ``element`` matches ``pattern``.

    With ``partial``, a dict pattern matches any dict that has the same values
    for the pattern's keys (other keys are ignored). Otherwise the values must
    be equal.
    """
    if partial and isinstance(pattern, dict):
        if not isinstance(element, dict):
            return False
        return all(k in element and element[k] == v for k, v in pattern.items())
    return element == pattern


# ---------------------------------------------------------------------------
# Scalar emission
# ---------------------------------------------------------------------------

def _loads_as(text, expected_plain, flow):
    """True when ``text``, used as a value, means ``expected_plain`` under YAML 1.1 and 1.2."""
    docs = ['k: %s\n' % text]
    if flow:
        docs.append('{k: %s}\n' % text)
        docs.append('k: [%s]\n' % text)
    for version in ((1, 1), (1, 2)):
        for doc in docs:
            try:
                data = _quiet_load(_safe_loader(version), doc)
            except Exception:
                return False
            if not isinstance(data, dict) or list(data.keys()) != ['k']:
                return False
            value = data['k']
            if doc.startswith('k: ['):
                if not isinstance(value, list) or len(value) != 1:
                    return False
                value = value[0]
            if to_plain(value) != expected_plain:
                return False
    return True


def _key_loads_as(text, expected):
    for version in ((1, 1), (1, 2)):
        try:
            data = _quiet_load(_safe_loader(version), '%s: 1\n' % text)
        except Exception:
            return False
        if not isinstance(data, dict) or len(data) != 1:
            return False
        k = list(data.keys())[0]
        if not isinstance(k, str) or k != expected:
            return False
    return True


def _single_quoted(s):
    return "'" + s.replace("'", "''") + "'"


def _is_yaml_printable(ch):
    cp = ord(ch)
    return (cp in (0x09, 0x0A, 0x0D) or 0x20 <= cp <= 0x7E or cp == 0x85
            or 0xA0 <= cp <= 0xD7FF or 0xE000 <= cp <= 0xFFFD or 0x10000 <= cp <= 0x10FFFF)


def _safe_char(ch):
    return _is_yaml_printable(ch) and not 0x80 <= ord(ch) <= 0x9F


def _double_quoted(s):
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        elif cp < 0x20 or cp == 0x7F or not _safe_char(ch):
            if cp <= 0xFF:
                out.append('\\x%02X' % cp)
            elif cp <= 0xFFFF:
                out.append('\\u%04X' % cp)
            else:
                out.append('\\U%08X' % cp)
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def _plain_candidate_ok(s, flow):
    if not s or s != s.strip() or s[0] in _PLAIN_FORBIDDEN_START:
        return False
    if any(ch in s for ch in '\n\r\t') or ': ' in s or ' #' in s or s.endswith(':'):
        return False
    if flow and any(ch in _FLOW_INDICATORS for ch in s):
        return False
    return all(_safe_char(ch) for ch in s)


def emit_string(s, prefer=None, flow=False):
    """Return a one-line YAML representation of string ``s`` that reads back as the same string."""
    expected = to_plain(s)
    if prefer == "'":
        candidates = ['single', 'double', 'plain']
    elif prefer == '"':
        candidates = ['double', 'single', 'plain']
    else:
        candidates = ['plain', 'single', 'double']
    for kind in candidates:
        if kind == 'plain':
            if not _plain_candidate_ok(s, flow):
                continue
            text = s
        elif kind == 'single':
            if any(ch in s for ch in '\n\r') or not all(_safe_char(ch) for ch in s):
                continue
            text = _single_quoted(s)
        else:
            text = _double_quoted(s)
        if _loads_as(text, expected, flow):
            return text
    raise YamlEditError('cannot represent the string %r as YAML' % (s,))


def emit_key(s):
    if _plain_candidate_ok(s, False) and _key_loads_as(s, s):
        return s
    for text in (_single_quoted(s), _double_quoted(s)):
        if _key_loads_as(text, s):
            return text
    raise YamlEditError('cannot represent the key %r as YAML' % (s,))


def emit_scalar(value, prefer=None, flow=False):
    """Return a one-line YAML representation of a scalar (or an empty collection)."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        if math.isnan(value):
            return '.nan'
        if math.isinf(value):
            return '.inf' if value > 0 else '-.inf'
        text = repr(float(value))
        mantissa, sep, exponent = text.partition('e')
        if '.' not in mantissa:
            mantissa += '.0'
        if sep and exponent[:1] not in '+-':
            exponent = '+' + exponent
        text = mantissa + sep + exponent
        if not _loads_as(text, to_plain(value), flow):
            raise YamlEditError('cannot represent the number %r as YAML' % (value,))
        return text
    if isinstance(value, str):
        return emit_string(value, prefer=prefer, flow=flow)
    if isinstance(value, dict) and not value:
        return '{}'
    if isinstance(value, list) and not value:
        return '[]'
    raise YamlEditError('unsupported value type %s' % type(value).__name__)


def is_inline(value):
    """True for values written on one line: scalars and empty collections."""
    return not isinstance(value, (dict, list)) or not value


def render_entry(key, value, col, indent, newline):
    """Render ``key: value`` as block YAML lines starting at column ``col``."""
    lines = []
    _render_entry(key, value, col, indent, lines)
    return newline.join(lines) + newline


def render_items(items, dash_col, indent, newline):
    """Render list items as block YAML lines with the dash at column ``dash_col``."""
    lines = []
    _render_sequence(items, dash_col, indent, lines)
    return newline.join(lines) + newline


def _render_entry(key, value, col, indent, lines):
    pad = ' ' * col
    ktext = emit_key(key)
    if is_inline(value):
        lines.append('%s%s: %s' % (pad, ktext, emit_scalar(value)))
    elif isinstance(value, dict):
        lines.append('%s%s:' % (pad, ktext))
        _render_mapping(value, col + indent[0], indent, lines)
    else:
        lines.append('%s%s:' % (pad, ktext))
        _render_sequence(value, col + indent[1], indent, lines)


def _render_mapping(mapping, col, indent, lines):
    for k, v in mapping.items():
        if not isinstance(k, str):
            raise YamlEditError('dictionary keys must be strings, got %s' % type(k).__name__)
        _render_entry(k, v, col, indent, lines)


def _render_sequence(seq, dash_col, indent, lines):
    item_col = dash_col + 2
    for item in seq:
        if is_inline(item):
            lines.append('%s- %s' % (' ' * dash_col, emit_scalar(item)))
            continue
        sub = []
        if isinstance(item, dict):
            _render_mapping(item, item_col, indent, sub)
        else:
            _render_sequence(item, item_col, indent, sub)
        sub[0] = ' ' * dash_col + '- ' + sub[0][item_col:]
        lines.extend(sub)


def guess_indent(roots):
    """Guess (mapping indent, sequence dash offset) from block collections in the documents."""
    mapping_indent = None
    seq_offset = None
    queue = [r for r in roots if r is not None]
    seen = set()
    while queue and (mapping_indent is None or seq_offset is None):
        node = queue.pop(0)
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, MappingNode):
            for k, v in node.value:
                if not node.flow_style and isinstance(v, MappingNode) and not v.flow_style and v.value \
                        and v.start_mark.line > k.start_mark.line and mapping_indent is None:
                    diff = v.value[0][0].start_mark.column - k.start_mark.column
                    if diff > 0:
                        mapping_indent = diff
                if not node.flow_style and isinstance(v, SequenceNode) and not v.flow_style and v.value \
                        and v.start_mark.line > k.start_mark.line and seq_offset is None:
                    diff = v.start_mark.column - k.start_mark.column
                    if diff >= 0:
                        seq_offset = diff
                queue.append(v)
        elif isinstance(node, SequenceNode):
            queue.extend(node.value)
    if mapping_indent is None:
        mapping_indent = 2
    if seq_offset is None:
        seq_offset = mapping_indent
    return mapping_indent, seq_offset


# ---------------------------------------------------------------------------
# Locating nodes
# ---------------------------------------------------------------------------

class Step(object):
    """One level of the key path that exists in the document."""

    def __init__(self, parent, node, key_node=None, index=None):
        self.parent = parent      # MappingNode or SequenceNode
        self.node = node          # the value node at this level
        self.key_node = key_node  # set for mapping entries
        self.index = index        # set for sequence items


class Location(object):
    def __init__(self, root):
        self.root = root
        self.steps = []
        self.missing_at = None   # index in the key path of the first missing part
        self.missing_reason = None

    @property
    def deepest(self):
        return self.steps[-1].node if self.steps else self.root

    @property
    def found(self):
        return self.missing_at is None


def locate(root, parts):
    loc = Location(root)
    node = root
    for i, part in enumerate(parts):
        if isinstance(node, MappingNode):
            if isinstance(part, int):
                raise YamlEditError('%s is a mapping, but the key path uses the list index [%d]'
                                    % (_describe(parts, i), part))
            k, v = find_key(node, part)
            if k is None:
                loc.missing_at = i
                loc.missing_reason = 'key'
                return loc
            loc.steps.append(Step(node, v, key_node=k))
            node = v
        elif isinstance(node, SequenceNode):
            if not isinstance(part, int):
                raise YamlEditError('%s is a list, but the key path uses the key %r; use an index such as [0]'
                                    % (_describe(parts, i), part))
            size = len(node.value)
            index = part + size if part < 0 else part
            if index < 0 or index >= size:
                loc.missing_at = i
                loc.missing_reason = 'index'
                return loc
            loc.steps.append(Step(node, node.value[index], index=index))
            node = node.value[index]
        elif _is_null(node):
            loc.missing_at = i
            loc.missing_reason = 'null'
            return loc
        else:
            raise YamlEditError('%s is a scalar value; it has no key %r' % (_describe(parts, i), part))
    return loc


def find_key(mapping, name):
    """Find the entry whose key text is ``name`` in a MappingNode. Returns (key_node, value_node)."""
    matches = [(k, v) for k, v in mapping.value if isinstance(k, ScalarNode) and k.value == name]
    if len(matches) > 1:
        raise YamlEditError('the key %r appears more than once in the same mapping' % (name,))
    if not matches:
        return None, None
    if matches[0][0].tag == 'tag:yaml.org,2002:merge':
        raise YamlEditError('merge keys (<<) cannot be edited with this module')
    return matches[0]


def _nest(parts, value):
    for part in reversed(parts):
        if isinstance(part, int):
            raise YamlEditError('cannot create the list item [%d]; only mapping keys can be created' % part)
        value = {part: value}
    return value


def _set_in(container, keys, setter):
    """Copy-on-write update of plain data along ``keys``."""
    if not keys:
        return setter(container)
    head = keys[0]
    new = copy.copy(container)
    new[head] = _set_in(container[head], keys[1:], setter)
    return new


def _get_in(container, keys):
    for k in keys:
        container = container[k]
    return container


# ---------------------------------------------------------------------------
# Text surgery helpers
# ---------------------------------------------------------------------------

def _colon_after_key(text, key_node):
    i = key_node.end_mark.index
    while i < len(text) and text[i] in ' \t':
        i += 1
    if i < len(text) and text[i] == ':':
        return i
    raise LosslessUnsupported('could not find the ":" after the key')


def _content_end(ctx, node, key_node=None):
    """Index just after the last character that belongs to ``node``."""
    text = ctx.text
    _refuse_alias(ctx, node)
    if _is_empty_null(node):
        if key_node is None:
            raise LosslessUnsupported('empty list item')
        return _colon_after_key(text, key_node) + 1
    if isinstance(node, ScalarNode) or node.flow_style:
        return node.end_mark.index
    if not node.value:
        raise LosslessUnsupported('empty block collection')
    if isinstance(node, MappingNode):
        k, v = node.value[-1]
        return _content_end(ctx, v, k)
    return _content_end(ctx, node.value[-1])


def _line_start(text, index):
    return text.rfind('\n', 0, index) + 1


def _after_line(text, index, newline):
    """Move ``index`` to the start of the next line. Returns (index, prefix to insert)."""
    if index == 0 or text[index - 1] == '\n':
        return index, ''
    nl = text.find('\n', index)
    if nl == -1:
        return len(text), newline
    return nl + 1, ''


def _own_line_start(text, index):
    """Start of the line containing ``index``, if only blanks precede ``index`` on that line."""
    start = _line_start(text, index)
    if text[start:index].strip(' \t'):
        raise LosslessUnsupported('the entry does not start its own line')
    return start


def _refuse_alias(ctx, node):
    """Alias nodes (``*name``) carry the position of their anchor, not their own: don't edit around them."""
    if id(node) in ctx.shared:
        raise LosslessUnsupported('the value contains a YAML alias (*name)')


def _dash_of(ctx, item):
    """Index of the "-" introducing a block sequence item."""
    text = ctx.text
    _refuse_alias(ctx, item)
    if _is_empty_null(item):
        raise LosslessUnsupported('empty list item')
    dash = text.rfind('-', 0, item.start_mark.index)
    if dash == -1 or text[dash + 1:item.start_mark.index].strip(' \t'):
        raise LosslessUnsupported('could not find the "-" of the list item')
    return dash


def _in_flow(loc, upto):
    return any(getattr(s.parent, 'flow_style', False) for s in loc.steps[:upto])


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def check_value(value, path='value'):
    """Only accept data that can be written as plain YAML."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise YamlEditError('%s: dictionary keys must be strings, got %s' % (path, type(k).__name__))
            check_value(v, '%s.%s' % (path, k))
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            check_value(v, '%s[%d]' % (path, i))
        return
    raise YamlEditError('%s: unsupported type %s' % (path, type(value).__name__))


def normalize_value(value):
    """Turn Ansible's str/int/dict subclasses into plain builtins."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, dict):
        return dict((str(k), normalize_value(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [normalize_value(v) for v in value]
    return value


def convert_value(value, value_type):
    if value_type == 'raw':
        check_value(value)
        return normalize_value(value)
    if value_type == 'null':
        if value is not None:
            raise YamlEditError('value must be omitted (or null) when value_type=null')
        return None
    if value is None or isinstance(value, (dict, list)):
        raise YamlEditError('value_type=%s needs a scalar value' % value_type)
    try:
        if value_type == 'str':
            if isinstance(value, bool):
                return 'true' if value else 'false'
            return str(value)
        if value_type == 'int':
            if isinstance(value, bool):
                raise ValueError()
            if isinstance(value, float):
                if not value.is_integer():
                    raise ValueError()
                return int(value)
            return int(str(value).strip(), 10)
        if value_type == 'float':
            if isinstance(value, bool):
                raise ValueError()
            return float(str(value).strip()) if isinstance(value, str) else float(value)
        if value_type == 'bool':
            return boolean(value, strict=True)
    except (TypeError, ValueError):
        raise YamlEditError('cannot convert %r to %s' % (value, value_type))
    raise YamlEditError('unknown value_type %s' % value_type)


def _to_rt_value(value):
    """Prepare a module value for ruamel.yaml, quoting strings that would be misread."""
    if isinstance(value, dict):
        out = CommentedMap()
        for k, v in value.items():
            out[_to_rt_value(k)] = _to_rt_value(v)
        return out
    if isinstance(value, list):
        out = CommentedSeq()
        for v in value:
            out.append(_to_rt_value(v))
        return out
    if isinstance(value, str):
        text = emit_string(value)
        if text.startswith("'"):
            return SingleQuotedScalarString(value)
        if text.startswith('"'):
            return DoubleQuotedScalarString(value)
    return value


# ---------------------------------------------------------------------------
# Edit context and runner
# ---------------------------------------------------------------------------

class Context(object):
    """A parsed YAML text, ready to plan one edit on one of its documents."""

    def __init__(self, text, yaml_version='1.2', document=0):
        self.text = text
        self.version = YAML_VERSIONS[yaml_version]
        self.newline = '\r\n' if '\r\n' in text else '\n'
        nodes = compose_documents(text, self.version)
        docs = load_documents(text, self.version)
        if len(nodes) != len(docs):
            raise YamlEditError('could not read the YAML documents consistently')
        if not nodes:
            nodes, docs = [None], [None]
        if document < 0 or document >= len(nodes):
            raise YamlEditError('document %d does not exist; the file has %d document(s)' % (document, len(nodes)))
        self.document = document
        self.nodes = nodes
        self.root = nodes[document]
        budget = _Budget()
        self.before = [to_plain(d, budget) for d in docs]
        self.shared = find_shared_nodes(self.root)
        self.indent = guess_indent(nodes)

    def locate(self, parts):
        loc = locate(self.root, parts)
        for node in [self.root] + [s.node for s in loc.steps]:
            if node is not None and id(node) in self.shared:
                raise YamlEditError(
                    'the key path goes through a value that is shared with a YAML anchor and alias '
                    '(&name / *name); changing it would also change the other places that use it')
        return loc

    def key_value(self, key_node):
        """Load the text of a key node on its own to get the Python key it stands for."""
        snippet = self.text[key_node.start_mark.index:key_node.end_mark.index]
        data = _quiet_load(_rt(self.version), '%s: null\n' % snippet)
        return list(data.keys())[0]

    def plain_keys(self, steps):
        return [_hashable(to_plain(self.key_value(s.key_node))) if s.key_node is not None else s.index
                for s in steps]

    def rt_keys(self, steps):
        return [self.key_value(s.key_node) if s.key_node is not None else s.index for s in steps]

    def plain_at(self, steps):
        return _get_in(self.before[self.document], self.plain_keys(steps))


class Plan(object):
    """What an edit must produce, and the two ways of producing it."""

    def __init__(self, expected_doc, lossless, roundtrip, check=None):
        self.expected_doc = expected_doc
        self.lossless = lossless      # callable() -> new text, may raise LosslessUnsupported
        self.roundtrip = roundtrip    # callable(docs) -> None, edits the loaded documents in place
        self.check = check            # optional callable(after_doc_plain) -> bool


class EditResult(object):
    def __init__(self, text, changed=False, method=None, **info):
        self.text = text
        self.changed = changed
        self.method = method
        self.info = info


def combine_methods(*methods):
    methods = [m for m in methods if m]
    if not methods:
        return None
    return 'roundtrip' if 'roundtrip' in methods else 'lossless'


def run_plan(ctx, plan, edit_mode):
    """Apply ``plan`` and return (new_text, method), or (text, None) when nothing changes."""
    if edit_mode not in ('auto', 'lossless', 'roundtrip'):
        raise YamlEditError('edit_mode must be auto, lossless or roundtrip')
    expected = list(ctx.before)
    expected[ctx.document] = plan.expected_doc
    if expected == ctx.before:
        return ctx.text, None

    def verify(new_text):
        try:
            after = load_documents(new_text, ctx.version)
        except YAMLError:
            return False
        if not after:
            after = [None]
        budget = _Budget()
        after = [to_plain(d, budget) for d in after]
        if after != expected:
            return False
        return plan.check is None or plan.check(after[ctx.document])

    reasons = []
    if edit_mode in ('auto', 'lossless'):
        try:
            new_text = plan.lossless()
            if verify(new_text):
                return new_text, 'lossless'
            reasons.append('the lossless edit did not produce the expected data')
        except LosslessUnsupported as e:
            reasons.append(str(e))
        if edit_mode == 'lossless':
            raise YamlEditError('a lossless edit is not possible (%s); use edit_mode=auto to allow '
                                'rewriting the file' % '; '.join(reasons))

    docs = load_documents(ctx.text, ctx.version) or [None]
    try:
        plan.roundtrip(docs)
    except LosslessUnsupported as e:
        raise YamlEditError('the edit is not possible: %s' % e)
    yaml = _rt_dumper(ctx.indent)
    yaml.explicit_start = bool(re.search(r'^---', ctx.text, re.MULTILINE))
    stream = io.StringIO()
    yaml.dump_all(docs, stream)
    new_text = stream.getvalue()
    if ctx.newline == '\r\n':
        new_text = new_text.replace('\r\n', '\n').replace('\n', '\r\n')
    if not verify(new_text):
        raise YamlEditError('the edit could not be verified, so the file was not changed (%s)'
                            % '; '.join(reasons + ['the round-trip result differs from the expected data']))
    return new_text, 'roundtrip'


def _rt_container(docs, document, keys):
    container = docs[document]
    for key in keys:
        container = container[key]
    return container


# ---------------------------------------------------------------------------
# Operation: set or remove a value (yaml_edit)
# ---------------------------------------------------------------------------

def edit_yaml_text(text, key, state='present', value=None, document=0, edit_mode='auto',
                   yaml_version='1.2', create=True, after=None, before=None):
    """Set or remove one value. Returns an EditResult with ``existed``, ``previous`` and ``value`` info."""
    if state not in ('present', 'absent'):
        raise YamlEditError('state must be present or absent')
    if after is not None and before is not None:
        raise YamlEditError('after and before are mutually exclusive')
    parts = parse_key(key)
    if state == 'present':
        check_value(value)
        value = normalize_value(value)
    ctx = Context(text, yaml_version, document)
    loc = ctx.locate(parts)
    plain_keys = ctx.plain_keys(loc.steps)
    existed = loc.found
    previous = plain_to_json(_get_in(ctx.before[document], plain_keys)) if existed else None
    result_value = plain_to_json(to_plain(value)) if state == 'present' else None

    def result(new_text, method):
        return EditResult(new_text, method is not None, method, existed=existed, previous=previous,
                          value=result_value)

    if state == 'absent':
        if after is not None or before is not None:
            raise YamlEditError('after and before can only be used with state=present')
        plan = _plan_delete(ctx, loc, parts, plain_keys)
        if plan is None:
            return result(text, None)
    elif existed:
        plan = _plan_replace(ctx, loc, plain_keys, value)
    else:
        if not create:
            raise YamlEditError('the key %s does not exist and create=false' % format_key(parts[:loc.missing_at + 1]))
        plan = _plan_create(ctx, loc, parts, plain_keys, value, after, before)
    return result(*run_plan(ctx, plan, edit_mode))


def _plan_replace(ctx, loc, plain_keys, value):
    plain_value = to_plain(value)
    expected = _set_in(ctx.before[ctx.document], plain_keys, lambda _old: plain_value)

    def lossless():
        if not loc.steps:
            raise LosslessUnsupported('replacing the whole document')
        return _lossless_replace(ctx, loc, loc.steps[-1], value, len(loc.steps))

    def roundtrip(docs):
        rt_keys = ctx.rt_keys(loc.steps)
        if not rt_keys:
            docs[ctx.document] = _to_rt_value(value)
        else:
            _rt_container(docs, ctx.document, rt_keys[:-1])[rt_keys[-1]] = _to_rt_value(value)

    return Plan(expected, lossless, roundtrip)


def _plan_create(ctx, loc, parts, plain_keys, value, after, before):
    i = loc.missing_at
    if loc.missing_reason == 'index':
        raise YamlEditError('the list item %s does not exist (list items are never created; '
                            'use yaml_list to add items)' % format_key(parts[:i + 1]))
    if isinstance(parts[i], int):
        raise YamlEditError('%s is null, so it has no list item [%d]' % (_describe(parts, i), parts[i]))
    new_key = parts[i]
    new_value = _nest(parts[i + 1:], value)
    nested = to_plain(new_value)

    sibling = after if after is not None else before
    where = 'after' if after is not None else 'before'
    sib_k = sib_v = None
    if sibling is not None:
        if not isinstance(sibling, str) or not sibling:
            raise YamlEditError('after and before must be the name of a key')
        parent = loc.deepest
        if i != len(parts) - 1 or not isinstance(parent, MappingNode):
            raise YamlEditError('after and before need the parent of %s to exist' % format_key(parts))
        sib_k, sib_v = find_key(parent, sibling)
        if sib_k is None:
            raise YamlEditError('the key %r given in %s does not exist next to %s'
                                % (sibling, where, format_key(parts)))
        sib_plain = _hashable(to_plain(ctx.key_value(sib_k)))

    def add(container):
        container = {} if container is None else container
        if sibling is None:
            new = dict(container)
            new[new_key] = nested
            return new
        new = {}
        for k, v in container.items():
            if k == sib_plain and where == 'before':
                new[new_key] = nested
            new[k] = v
            if k == sib_plain and where == 'after':
                new[new_key] = nested
        return new

    expected = _set_in(ctx.before[ctx.document], plain_keys, add)

    def check(after_doc):
        if sibling is None:
            return True
        keys = list(_get_in(after_doc, plain_keys).keys())
        offset = 1 if where == 'after' else -1
        return keys.index(new_key) == keys.index(sib_plain) + offset

    def lossless():
        text, newline, indent = ctx.text, ctx.newline, ctx.indent
        if loc.missing_reason == 'null':
            if not loc.steps:
                raise LosslessUnsupported('the document is empty')
            return _lossless_replace(ctx, loc, loc.steps[-1], {new_key: new_value}, len(loc.steps))
        parent = loc.deepest
        if parent.flow_style or _in_flow(loc, len(loc.steps)):
            raise LosslessUnsupported('adding a key to an inline {...} mapping')
        if sibling is None:
            col = parent.value[0][0].start_mark.column
            last_k, last_v = parent.value[-1]
            pos, prefix = _after_line(text, _content_end(ctx, last_v, last_k), newline)
        else:
            col = sib_k.start_mark.column
            if where == 'before':
                pos, prefix = _own_line_start(text, sib_k.start_mark.index), ''
            else:
                pos, prefix = _after_line(text, _content_end(ctx, sib_v, sib_k), newline)
        block = render_entry(new_key, new_value, col, indent, newline)
        return text[:pos] + prefix + block + text[pos:]

    def roundtrip(docs):
        rt_keys = ctx.rt_keys(loc.steps)
        rt_value = _to_rt_value(new_value)
        rt_key = _to_rt_value(new_key)
        if not rt_keys:
            if docs[ctx.document] is None:
                docs[ctx.document] = CommentedMap()
            container = docs[ctx.document]
        else:
            holder = _rt_container(docs, ctx.document, rt_keys[:-1])
            if holder[rt_keys[-1]] is None:
                holder[rt_keys[-1]] = CommentedMap()
            container = holder[rt_keys[-1]]
        if sibling is None:
            container[rt_key] = rt_value
        else:
            pos = list(container.keys()).index(ctx.key_value(sib_k)) + (1 if where == 'after' else 0)
            container.insert(pos, rt_key, rt_value)

    return Plan(expected, lossless, roundtrip, check)


def _plan_delete(ctx, loc, parts, plain_keys):
    if not loc.found:
        # Nothing to remove, unless the key is only inherited through a merge key.
        if loc.missing_reason == 'key' and loc.missing_at == len(parts) - 1:
            container = _get_in(ctx.before[ctx.document], plain_keys)
            if isinstance(container, dict) and parts[-1] in container:
                raise YamlEditError('the key %s is inherited through a merge key (<<) and cannot be removed'
                                    % format_key(parts))
        return None
    if not loc.steps:
        raise YamlEditError('cannot remove the document root')

    def remove(container, last=plain_keys[-1]):
        container = copy.copy(container)
        del container[last]
        return container
    expected = _set_in(ctx.before[ctx.document], plain_keys[:-1], remove)

    def lossless():
        return _lossless_delete(ctx, loc)

    def roundtrip(docs):
        rt_keys = ctx.rt_keys(loc.steps)
        container = _rt_container(docs, ctx.document, rt_keys[:-1])
        if isinstance(container, dict) and getattr(container, 'merge', None):
            raise LosslessUnsupported('removing a key from a mapping that uses a merge key (<<)')
        del container[rt_keys[-1]]

    return Plan(expected, lossless, roundtrip)


def _lossless_replace(ctx, loc, step, value, depth):
    text, newline, indent = ctx.text, ctx.newline, ctx.indent
    target = step.node
    flow = _in_flow(loc, depth)

    # Scalar replaced by a scalar (or an empty collection): rewrite just the value.
    if isinstance(target, ScalarNode) and is_inline(value):
        if target.style in ('|', '>'):
            raise LosslessUnsupported('replacing a block scalar (| or >)')
        prefer = target.style if target.style in ("'", '"') else None
        new = emit_scalar(value, prefer=prefer, flow=flow)
        if _is_empty_null(target):
            if step.key_node is None:
                raise LosslessUnsupported('empty list item')
            colon = _colon_after_key(text, step.key_node)
            return text[:colon + 1] + ' ' + new + text[colon + 1:]
        start, end = target.start_mark.index, target.end_mark.index
        if '\n' in text[start:end]:
            raise LosslessUnsupported('replacing a multi-line scalar')
        return text[:start] + new + text[end:]

    # A collection is involved: rewrite everything after "key:".
    if step.key_node is None:
        raise LosslessUnsupported('replacing a list item that is or becomes a collection')
    if flow:
        raise LosslessUnsupported('replacing a value inside an inline {...} or [...] collection')
    if isinstance(target, ScalarNode) and target.style in ('|', '>'):
        raise LosslessUnsupported('replacing a block scalar (| or >)')
    colon = _colon_after_key(text, step.key_node)
    end = _content_end(ctx, target, step.key_node)
    if is_inline(value):
        return text[:colon + 1] + ' ' + emit_scalar(value) + text[end:]
    col = step.key_node.start_mark.column
    lines = []
    if isinstance(value, dict):
        _render_mapping(value, col + indent[0], indent, lines)
    else:
        _render_sequence(value, col + indent[1], indent, lines)
    return text[:colon + 1] + newline + newline.join(lines) + text[end:]


def _lossless_delete(ctx, loc):
    text, newline = ctx.text, ctx.newline
    step = loc.steps[-1]
    parent = step.parent
    if parent.flow_style or _in_flow(loc, len(loc.steps)):
        raise LosslessUnsupported('removing from an inline {...} or [...] collection')
    if len(parent.value) == 1:
        # Removing the only entry: the parent becomes an empty collection.
        if len(loc.steps) < 2:
            raise LosslessUnsupported('removing the only entry of the document')
        empty = {} if isinstance(parent, MappingNode) else []
        return _lossless_replace(ctx, loc, loc.steps[-2], empty, len(loc.steps) - 1)
    if step.key_node is not None:
        start = step.key_node.start_mark.index
        end = _content_end(ctx, step.node, step.key_node)
    else:
        start = _dash_of(ctx, step.node)
        end = _content_end(ctx, step.node)
    line_start = _line_start(text, start)
    prefix = text[line_start:start]
    if prefix.strip(' \t') == '-' and step.key_node is not None and step.key_node is parent.value[0][0]:
        # First key of a list item ("- a: 1"): the next key moves up after the dash.
        next_key = parent.value[1][0]
        return text[:start] + text[next_key.start_mark.index:]
    if prefix.strip(' \t'):
        raise LosslessUnsupported('the entry does not start its own line')
    end = _after_line(text, end, newline)[0]
    return text[:line_start] + text[end:]


# ---------------------------------------------------------------------------
# Operation: insert an item into a list (yaml_list)
# ---------------------------------------------------------------------------

def insert_item_text(text, list_key, index, item, document=0, edit_mode='auto', yaml_version='1.2'):
    """Insert ``item`` at ``index`` (0 to len) in an existing list."""
    check_value(item, 'item')
    item = normalize_value(item)
    parts = parse_key(list_key, allow_empty=True)
    ctx = Context(text, yaml_version, document)
    loc = ctx.locate(parts)
    seq = loc.deepest
    if not loc.found or not isinstance(seq, SequenceNode):
        raise YamlEditError('%s is not a list' % format_key(parts))
    if index < 0 or index > len(seq.value):
        raise YamlEditError('index %d is out of range for a list of %d item(s)' % (index, len(seq.value)))
    plain_keys = ctx.plain_keys(loc.steps)
    plain_item = to_plain(item)

    def insert(lst):
        lst = list(lst)
        lst.insert(index, plain_item)
        return lst
    expected = _set_in(ctx.before[document], plain_keys, insert)

    def lossless():
        return _lossless_insert(ctx, loc, seq, index, item)

    def roundtrip(docs):
        rt_keys = ctx.rt_keys(loc.steps)
        _rt_container(docs, document, rt_keys).insert(index, _to_rt_value(item))

    new_text, method = run_plan(ctx, Plan(expected, lossless, roundtrip), edit_mode)
    return EditResult(new_text, method is not None, method, index=index)


def _lossless_insert(ctx, loc, seq, index, item):
    text, newline = ctx.text, ctx.newline
    items = seq.value
    if seq.flow_style or _in_flow(loc, len(loc.steps)):
        if not is_inline(item):
            raise LosslessUnsupported('adding a dictionary or list to an inline [...] list')
        new = emit_scalar(item, flow=True)
        if not items:
            bracket = text.find('[', seq.start_mark.index, seq.end_mark.index)
            if bracket == -1:
                raise LosslessUnsupported('could not find the "[" of the list')
            return text[:bracket + 1] + new + text[bracket + 1:]
        if index < len(items):
            pos = items[index].start_mark.index
            return text[:pos] + new + ', ' + text[pos:]
        pos = _content_end(ctx, items[-1])
        return text[:pos] + ', ' + new + text[pos:]

    first_dash = _dash_of(ctx, items[0])
    dash_col = first_dash - _own_line_start(text, first_dash)
    block = render_items([item], dash_col, ctx.indent, newline)
    if index < len(items):
        pos = _own_line_start(text, _dash_of(ctx, items[index]))
        return text[:pos] + block + text[pos:]
    pos, prefix = _after_line(text, _content_end(ctx, items[-1]), newline)
    return text[:pos] + prefix + block + text[pos:]


# ---------------------------------------------------------------------------
# High-level list operations (yaml_list)
# ---------------------------------------------------------------------------

def _list_state(text, parts, document, yaml_version):
    """Return (ctx, loc, plain list or None) for the list at ``parts``."""
    ctx = Context(text, yaml_version, document)
    loc = ctx.locate(parts)
    if not loc.found:
        if loc.missing_reason == 'index':
            raise YamlEditError('the list item %s does not exist' % format_key(parts[:loc.missing_at + 1]))
        return ctx, loc, None
    node = loc.deepest
    if _is_null(node):
        return ctx, loc, None
    if not isinstance(node, SequenceNode):
        raise YamlEditError('%s is not a list' % format_key(parts))
    return ctx, loc, ctx.plain_at(loc.steps)


def _item_pattern(item, identify_by):
    """The pattern that identifies ``item`` in a list, and whether it is a partial match."""
    if not identify_by:
        return to_plain(item), False
    if not isinstance(item, dict):
        raise YamlEditError('identify_by needs item to be a dictionary')
    missing = [f for f in identify_by if f not in item]
    if missing:
        raise YamlEditError('item has no %s field, which identify_by needs' % ', '.join(repr(f) for f in missing))
    return to_plain(dict((f, item[f]) for f in identify_by)), True


def ensure_list_item(text, list_key, item, identify_by=None, position='end', index=None,
                     after=None, before=None, create=True, document=0, edit_mode='auto', yaml_version='1.2'):
    """Make sure ``item`` is in the list. Returns an EditResult with ``action`` and ``index`` info.

    Without ``identify_by``, an equal item is enough: nothing changes. With
    ``identify_by``, the item whose fields match is replaced by ``item`` when
    it differs, or ``item`` is added when no item matches.
    """
    check_value(item, 'item')
    item = normalize_value(item)
    identify_by = list(identify_by or [])
    if sum(x is not None for x in (index, after, before)) + (position not in (None, 'end')) > 1:
        raise YamlEditError('position, index, after and before are mutually exclusive')
    parts = parse_key(list_key, allow_empty=True)
    ctx, loc, current = _list_state(text, parts, document, yaml_version)
    pattern, partial = _item_pattern(item, identify_by)
    plain_item = to_plain(item)

    if current is None:
        if not create:
            raise YamlEditError('the list %s does not exist and create=false' % format_key(parts))
        if not parts:
            raise YamlEditError('the document is empty; it cannot be turned into a list by yaml_list')
        if after is not None or before is not None:
            raise YamlEditError('the list %s does not exist, so after/before cannot be found' % format_key(parts))
        res = edit_yaml_text(text, parts, value=[item], document=document, edit_mode=edit_mode,
                             yaml_version=yaml_version)
        return EditResult(res.text, res.changed, res.method, action='created', index=0)

    matches = [i for i, element in enumerate(current) if plain_matches(element, pattern, partial)]
    if partial and len(matches) > 1:
        raise YamlEditError('%d items of %s match identify_by %s; they must be unique'
                            % (len(matches), format_key(parts), identify_by))
    if matches:
        i = matches[0]
        if current[i] == plain_item:
            return EditResult(text, False, None, action='unchanged', index=i)
        # Update the matching item in place.
        if is_inline(item):
            res = edit_yaml_text(text, parts + [i], value=item, document=document, edit_mode=edit_mode,
                                 yaml_version=yaml_version)
            return EditResult(res.text, True, res.method, action='updated', index=i)
        first = insert_item_text(text, parts, i, item, document, edit_mode, yaml_version)
        second = edit_yaml_text(first.text, parts + [i + 1], state='absent', document=document,
                                edit_mode=edit_mode, yaml_version=yaml_version)
        return EditResult(second.text, True, combine_methods(first.method, second.method), action='updated', index=i)

    target = _insert_position(current, parts, position, index, after, before)
    res = insert_item_text(text, parts, target, item, document, edit_mode, yaml_version)
    return EditResult(res.text, True, res.method, action='added', index=target)


def _insert_position(current, parts, position, index, after, before):
    if index is not None:
        if isinstance(index, bool) or not isinstance(index, int):
            raise YamlEditError('index must be an integer')
        if index < 0 or index > len(current):
            raise YamlEditError('index %d is out of range for %s, which has %d item(s)'
                                % (index, format_key(parts), len(current)))
        return index
    for anchor, offset, name in ((after, 1, 'after'), (before, 0, 'before')):
        if anchor is None:
            continue
        check_value(anchor, name)
        pattern = to_plain(normalize_value(anchor))
        for i, element in enumerate(current):
            if plain_matches(element, pattern, True):
                return i + offset
        raise YamlEditError('no item of %s matches %s=%r' % (format_key(parts), name, anchor))
    if position == 'start':
        return 0
    if position in (None, 'end'):
        return len(current)
    raise YamlEditError('position must be start or end')


def remove_list_items(text, list_key, item, identify_by=None, document=0, edit_mode='auto', yaml_version='1.2'):
    """Remove every item that matches ``item`` (or its ``identify_by`` fields)."""
    check_value(item, 'item')
    item = normalize_value(item)
    parts = parse_key(list_key, allow_empty=True)
    ctx, loc, current = _list_state(text, parts, document, yaml_version)
    if current is None:
        return EditResult(text, False, None, action='unchanged', removed=0)
    pattern, partial = _item_pattern(item, identify_by)
    matches = [i for i, element in enumerate(current) if plain_matches(element, pattern, partial)]
    methods = []
    for i in reversed(matches):
        res = edit_yaml_text(text, parts + [i], state='absent', document=document, edit_mode=edit_mode,
                             yaml_version=yaml_version)
        text = res.text
        methods.append(res.method)
    if not matches:
        return EditResult(text, False, None, action='unchanged', removed=0)
    return EditResult(text, True, combine_methods(*methods), action='removed', removed=len(matches))


# ---------------------------------------------------------------------------
# File handling, shared by the modules
# ---------------------------------------------------------------------------

_BOM = b'\xef\xbb\xbf'


def read_yaml_file(path):
    with open(path, 'rb') as f:
        data = f.read()
    bom = data.startswith(_BOM)
    if bom:
        data = data[len(_BOM):]
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        raise YamlEditError('%s is UTF-16 encoded; only UTF-8 is supported' % path)
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as e:
        raise YamlEditError('%s is not valid UTF-8 (byte %d)' % (path, e.start))
    return text, bom


def describe_yaml_error(e):
    """Summarise a parse error without echoing file content, which may be secret."""
    if HAS_RUAMEL and isinstance(e, MarkedYAMLError):
        mark = e.problem_mark or e.context_mark
        where = ' at line %d, column %d' % (mark.line + 1, mark.column + 1) if mark else ''
        problem = e.problem or e.context or 'invalid YAML'
        return 'cannot parse the YAML file: %s%s' % (problem, where)
    return 'cannot parse the YAML file (%s)' % type(e).__name__


def _write_atomically(module, real_path, data):
    """Write ``data`` next to the target, validate it, then move it into place."""
    directory = os.path.dirname(real_path) or '.'
    fd, tmp_path = tempfile.mkstemp(prefix='.%s.' % os.path.basename(real_path), suffix='.tmp', dir=directory)
    try:
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        validate = module.params['validate']
        if validate:
            argv = [arg.replace('%s', tmp_path) for arg in shlex.split(validate)]
            rc, out, err = module.run_command(argv)
            if rc != 0:
                module.fail_json(msg='validation failed with return code %d' % rc,
                                 validate_stdout=out, validate_stderr=err, rc=rc)
        module.atomic_move(tmp_path, real_path, unsafe_writes=module.params['unsafe_writes'])
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def run_file_edit(module, edit, result):
    """Read the file, call ``edit(text) -> EditResult``, write the result and exit the module.

    ``result`` holds the module's return values; ``edit`` may add to it. This
    handles check mode, diff mode, backups, validation, atomic writes, file
    attributes and error reporting for every module of the collection.
    """
    if not HAS_RUAMEL:
        from ansible.module_utils.basic import missing_required_lib
        module.fail_json(msg=missing_required_lib('ruamel.yaml'), exception=RUAMEL_IMPORT_ERROR)

    params = module.params
    path = params['path']
    validate = params['validate']
    if validate and '%s' not in validate:
        module.fail_json(msg='validate must contain %%s: %s' % validate)
    result.setdefault('changed', False)
    result.setdefault('method', None)
    result['path'] = path

    try:
        if not os.path.exists(to_bytes(path, errors='surrogate_or_strict')):
            raise YamlEditError('the file %s does not exist' % path)
        real_path = os.path.realpath(path)
        if os.path.isdir(real_path):
            raise YamlEditError('%s is a directory' % path)
        result['path'] = real_path
        text, bom = read_yaml_file(real_path)
        outcome = edit(text)
    except YamlEditError as e:
        module.fail_json(msg=to_native(e), **result)
    except YAMLError as e:
        module.fail_json(msg=describe_yaml_error(e), **result)
    except RecursionError:
        module.fail_json(msg='the YAML document is too deeply nested', **result)
    except (IOError, OSError) as e:
        module.fail_json(msg='cannot read %s: %s' % (path, to_native(e)), **result)

    result['changed'] = outcome.changed
    result['method'] = outcome.method
    if outcome.changed:
        if module._diff:
            result['diff'] = dict(before_header=real_path, after_header=real_path,
                                  before=text, after=outcome.text)
        if not module.check_mode:
            data = outcome.text.encode('utf-8')
            if bom:
                data = _BOM + data
            if params['backup']:
                result['backup_file'] = module.backup_local(real_path)
            try:
                _write_atomically(module, real_path, data)
            except (IOError, OSError) as e:
                module.fail_json(msg='cannot write %s: %s' % (real_path, to_native(e)), **result)

    file_args = module.load_file_common_arguments(params, path=real_path)
    result['changed'] = module.set_fs_attributes_if_different(file_args, result['changed'])
    module.exit_json(**result)
