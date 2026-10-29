# Security policy

## Supported versions

Security fixes are made on the latest release only.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report them privately through GitHub:
**Security → Report a vulnerability** on this repository
(GitHub private vulnerability reporting).

Include:

- a description of the problem and its impact,
- the steps or a minimal YAML file and task that reproduce it,
- the versions of ansible-core, Python and ruamel.yaml.

You will get an answer within 7 days. Once a fix is released, the report is
published as a GitHub security advisory, with credit if you want it.

## Scope

In scope: anything that lets a YAML file or a task argument make the module
run code, write outside the target file, leak file content in error messages,
exhaust memory or CPU, or write data other than what was requested.

Out of scope: content shown on purpose in the diff or in the `value` and
`previous_value` return values. Use `no_log: true` on tasks that handle secrets.
