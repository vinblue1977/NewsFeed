"""Bundling for the ingest Lambda: the `backend/` code plus the packages in requirements-lambda.txt.

The Lambda runtime ships boto3 and nothing else, so `cryptography` (Web Push) has to travel with the code. The packages are
installed for the Lambda's platform (Linux, ARM64) with pip's `--platform` option, from the hashed lockfile (`--require-hashes`,
wheels only), so there is no Docker and no compiler, and what is installed is exactly what was audited. The result is cached by
the hash of the lockfile, the platforms and the Python version, so repeated synths (and the tests) install once."""

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import jsii
from aws_cdk import AssetHashType, BundlingOptions, ILocalBundling
from aws_cdk import aws_lambda as lambda_

# manylinux tags a wheel for Amazon Linux 2023 (glibc 2.34) on ARM64 may carry.
PLATFORMS = ("manylinux2014_aarch64", "manylinux_2_28_aarch64", "manylinux_2_34_aarch64")
PYTHON_VERSION = "3.14"  # the Lambda runtime in stack.py
CACHE = Path(".cache/lambda-deps")  # gitignored


def install_dependencies(requirements: Path, cache: Path = CACHE) -> Path:
    """The folder holding the installed packages for `requirements`: built once per lockfile, platform and Python version."""
    wanted = requirements.read_bytes() + repr((PLATFORMS, PYTHON_VERSION)).encode()
    digest = hashlib.sha256(wanted).hexdigest()[:16]
    target = cache / digest
    if target.is_dir():
        return target
    cache.mkdir(parents=True, exist_ok=True)
    building = Path(tempfile.mkdtemp(prefix=digest + ".", suffix=".tmp", dir=cache))  # unique: parallel synths do not collide
    command = [
        sys.executable, "-m", "pip", "install",
        "--quiet", "--no-input", "--disable-pip-version-check", "--no-compile",
        "--require-hashes", "--only-binary=:all:", "--no-deps",
        "--implementation", "cp", "--python-version", PYTHON_VERSION,
        "--target", str(building), "-r", str(requirements),
    ]  # fmt: skip
    for platform in PLATFORMS:
        command += ["--platform", platform]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        shutil.rmtree(building, ignore_errors=True)
        raise RuntimeError(f"could not install the Lambda packages:\n{result.stderr[-2000:]}")
    try:
        building.rename(target)
    except OSError:  # a parallel synth finished first: its folder is identical
        shutil.rmtree(building, ignore_errors=True)
        if not target.is_dir():
            raise
    return target


@jsii.implements(ILocalBundling)
class LocalDependencies:
    """Copies the code, then the installed packages, into the asset folder. Returns True so CDK never needs Docker."""

    def __init__(self, source: Path, requirements: Path) -> None:
        self.source = source
        self.requirements = requirements

    def try_bundle(
        self, output_dir: str, *_args: Any, **_options: Any
    ) -> bool:  # jsii passes the options positionally or by name
        packages = install_dependencies(self.requirements)
        out = Path(output_dir)
        shutil.copytree(packages, out, dirs_exist_ok=True)
        shutil.copytree(self.source, out, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return True


def ingest_code(source: str = "backend", requirements: str = "requirements-lambda.txt") -> lambda_.AssetCode:
    """The Lambda code asset. Its hash is that of the bundled output, so a package update changes the deployed code."""
    return lambda_.Code.from_asset(
        source,
        asset_hash_type=AssetHashType.OUTPUT,
        bundling=BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_14.bundling_image,  # required by the API; never pulled, local bundling succeeds
            local=LocalDependencies(Path(source).resolve(), Path(requirements).resolve()),
        ),
    )
