# Security Policy

## Supported versions

`portfolio` is early-stage (`0.x`). Only the latest release (currently **v0.2.0**)
and `main` are supported; fixes land on `main`, not on older tags.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue for
anything exploitable.

- Use GitHub's **private vulnerability reporting**: the **Security** tab →
  **Report a vulnerability** on this repository. This opens a private advisory
  visible only to maintainers.

Please include: what you found, how to reproduce it, and the impact. We aim to
acknowledge a report within a few days and to coordinate a fix and disclosure
timeline with you.

## Scope notes

This tool shells out to the GitHub CLI (`gh`) and invokes a model runner.
Reports we especially care about:

- Any path where untrusted input (a repo URL, author handle, JD text, or fetched
  web content) reaches a shell, `subprocess` with `shell=True`, or command
  interpolation. The extractor is designed to pass arguments as argv tokens, never
  as an assembled shell string — a regression here is a security bug.
- Any way to make the **grounding gate** ship a claim that cites evidence the
  extractor never produced (a bypass of "every claim must be grounded").
- Leakage of secrets, tokens, or local filesystem paths into rendered output.
