# Repository Instructions

These instructions apply to the entire repository.

## Scope and architecture

- Preserve the phased architecture documented in `README.md` and ADR-0004.
- Do not describe planned capabilities as implemented.
- Keep bootstrap, platform configuration, application code, and documentation clearly separated.
- Record consequential, durable architecture choices as ADRs.

## Engineering standards

- Prefer small, reviewable changes and portable automation.
- Scripts must be idempotent, use strict error handling, and provide actionable errors.
- Never commit credentials, kubeconfigs, private keys, generated secrets, or local environment files.
- Pin third-party CI actions to full commit SHAs and retain a human-readable version comment.
- Run `make validate` before handing off changes.
- Do not install dependencies or mutate infrastructure as part of validation.

## Documentation

- Use concise, technically accurate language.
- Explain current behavior separately from future intent.
- Keep internal links relative and valid.
- Update the changelog for user-visible changes.
