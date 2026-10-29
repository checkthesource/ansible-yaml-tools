# -*- coding: utf-8 -*-

# Copyright (c) the yaml_tools contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type


class ModuleDocFragment(object):
    """Options shared by every module of the yaml_tools collection."""

    DOCUMENTATION = r'''
options:
  path:
    description:
      - Path of the YAML file to edit. The file must already exist.
      - Symbolic links are followed; the link target is edited and the link is kept.
    type: path
    required: true
    aliases: [dest]
  document:
    description:
      - Index of the document to edit in a multi-document file (documents
        separated by C(---)). The first document is V(0).
    type: int
    default: 0
  edit_mode:
    description:
      - V(auto) tries a lossless edit first and falls back to a round-trip edit
        when the lossless edit is not possible.
      - V(lossless) only allows lossless edits and fails otherwise. Use this
        when the formatting of the file must never change.
      - V(roundtrip) always rewrites the document with C(ruamel.yaml). Comments
        and key order are kept, but formatting may be normalised.
      - The method actually used is returned in RV(method).
    type: str
    choices: [auto, lossless, roundtrip]
    default: auto
  yaml_version:
    description:
      - YAML version used to read the file, which matters for values such as
        C(yes), C(on) or C(0777).
      - Under V(1.1) (the version used by Ansible and PyYAML) C(yes) is a boolean.
        Under V(1.2) it is a string.
      - A C(%YAML) directive in the file takes precedence.
      - Written strings are always quoted when they could be misread under
        either version, so the files stay unambiguous.
    type: str
    choices: ['1.1', '1.2']
    default: '1.2'
  backup:
    description:
      - Create a backup file including the timestamp information so you can
        get the original file back if you somehow clobbered it incorrectly.
    type: bool
    default: false
  validate:
    description:
      - Command used to validate the new file before it replaces the original.
      - The path of the temporary file is given with C(%s), which must be present.
      - The command is run without a shell, so shell features such as pipes or
        redirections are not available, and the file path cannot be used to
        inject commands.
    type: str
attributes:
  check_mode:
    support: full
    description: Can run in check mode and return changed status prediction without modifying target.
  diff_mode:
    support: full
    description: Will return details on what has changed (or possibly needs changing in check_mode), when in diff mode.
  platform:
    support: full
    platforms: posix
    description: Target OS/families that can be operated against.
requirements:
  - ruamel.yaml >= 0.17 (on the managed node)
notes:
  - Files must be UTF-8 encoded (with or without a byte order mark).
    Windows (CRLF) line endings are preserved.
  - Every edit is verified before it is written. The new file is parsed again
    and must contain exactly the expected data, with nothing else changed.
    If that check fails, the file is left untouched.
  - Values reached through a YAML alias (C(*name)), or anchored values that
    are referenced elsewhere, are refused, because changing them would also
    change every other place that uses them.
  - "The diff and the values returned by the module contain file content.
    Use C(no_log: true) on the task when the file holds secrets."
  - A round-trip edit does not preserve C(%YAML) directives, document end
    markers (C(...)) or irregular indentation.
'''
