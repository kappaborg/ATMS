"""
Setup script for ATMS Shared Package
Install in development mode: pip install -e .
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read the version
version = "1.0.0"

# Get all packages
packages = ["shared"] + [f"shared.{pkg}" for pkg in ["models", "utils", "middleware", "proto"]]

setup(
    name="atms-shared",
    version=version,
    description="Shared utilities and models for ATMS microservices",
    author="ATMS Team",
    py_modules=["shared"],
    packages=packages,
    package_dir={"": str(Path(__file__).parent.parent)},
    python_requires=">=3.11",
    install_requires=[
        "pydantic>=2.0.0",
        "structlog>=23.1.0",
        "python-json-logger>=2.0.7",
        # OpenTelemetry instrumentation imports `packaging` at runtime; it is
        # normally bundled with pip but is NOT copied into the slim runtime
        # image stage (only /root/.local is), so declare it explicitly.
        "packaging>=21.0",
    ],
)

