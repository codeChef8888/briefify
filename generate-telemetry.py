"""Compatibility entrypoint for telemetry generation.

This file intentionally remains at repository root for discoverability.
The implementation source of truth lives in scripts/generate_telemetry.py.
"""

from scripts.generate_telemetry import generate_telemetry_dataset


if __name__ == "__main__":
    generate_telemetry_dataset()