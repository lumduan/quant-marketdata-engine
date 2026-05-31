# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Bootstrapped `quant-marketdata-engine` from `lumduan/python-template`: renamed
  package to `src/quant_marketdata_engine/`, personalised `pyproject.toml`, bumped the
  coverage gate to ≥90%.
- `docs/plans/ROADMAP.md` — per-service roadmap (Phase 0–5) for the canonical OHLCV
  store + sole tvkit-cookie owner, derived from the umbrella
  `plans/feature-market-data-engine/` design docs.
- `CLAUDE.md` — per-service AI-agent guide (ownership boundaries, ports, conventions).
- `.claude/knowledge/market-data-engine.md` and
  `.claude/playbooks/development-workflow.md` — domain context + dev playbook.
- `.env.example` documenting `TVKIT_AUTH_TOKEN` (cookie JSON, never committed),
  public/private mode, infra-db DSN, own-Redis URL.

> **Scaffold only.** No market-data fetch/storage/read-API/Redis logic yet — that
> build-out is sequenced in `docs/plans/ROADMAP.md` (Phase 2+), gated on the Phase 0 ADR.

[Unreleased]: https://github.com/lumduan/quant-marketdata-engine/compare/HEAD...HEAD
