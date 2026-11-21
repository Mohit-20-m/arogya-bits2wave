# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-22

The trained model and the complete backend platform.

### Model
- Lesion triage model v1.0.0: EfficientNetV2-S, calibrated probability, CAM heat map, embedding and
  out-of-distribution statistics; ONNX FP32 and INT8 for CPU inference.
- Held-out test set (346 photographs): AUC 0.969, sensitivity 0.914, specificity 0.950 at the screening threshold.
- Training pipeline (`training/`), the Kaggle training notebook, model card, integration contract and evaluation
  reports. Weights are published as release assets and verified by `scripts/fetch-model.sh`.

### Platform
- API, inference service, worker and decision engine; PostgreSQL with row-level security, MinIO, Keycloak, OPA,
  Vault and Traefik in one Docker Compose stack.
- Decision logic v2: findings, exposure and confidence answered separately, AI evidence bands, fail-safe rules,
  plain-language summaries with the model's validated accuracy; 26 example patients as automated tests. Rule set v1
  is kept for exact replay of older decisions.
- Care after the result: sourced habit-risk facts and a personal roadmap (English, Kannada, Hindi) with progress
  recorded on visits.
- Real hospitals near the patient from OpenStreetMap with road travel times (OSRM), hospital choice for the
  referral, and a map tile proxy. Only map coordinates leave the system.
- Monitoring: service health checks every minute, uptime history, host load and alerts.
- Privacy (DPDP Act): versioned consent texts, separate messaging consent, guardian consent for minors, data export,
  erasure, nightly retention, grievance contact, messaging allowlist and daily cap.
- Specialist workflow, referrals and appointments, FHIR R4 resources, hash-chained audit log and MLOps (head
  retraining, benchmark, shadow mode, promotion and rollback).

[Unreleased]: https://github.com/Mohit-20-m/arogya-bits2wave/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Mohit-20-m/arogya-bits2wave/releases/tag/v0.1.0
