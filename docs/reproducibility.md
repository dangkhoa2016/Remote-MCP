# Reproducibility

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](reproducibility.vi.md)

## Source identity

Public notebook runs print the selected Git ref and exact commit SHA.

## Model identity

Runtime weights come only from the attached Kaggle Model. The resolver stays under `/kaggle/input` and validates the local model layout.

## Data identity

Canonical datasets and Quick Demo indexes carry checksums, row counts, dimensions and provenance metadata.

## Fresh-session policy

Full production acceptance and qualification should run in separate fresh Kaggle sessions. Do not reuse mutable `/kaggle/working` state between them.

## Release artifacts

Release archives are scanned, re-extracted, checksum-verified, and generated from the publication revision.

## Evidence interpretation

Historical GPU evidence remains historical evidence for its exact SHA. Documentation or presentation-only amendments can be validated offline; executable changes require an appropriate rerun.
