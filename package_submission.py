"""Automated Submission Packaging Script for NetCoop AI.

Packages the clean, verified source code, documentation, and test suites into a
submission-ready ZIP file (NetCoop_AI_Submission.zip) while strictly omitting:
- .git metadata and commit histories
- __pycache__ bytecode and cached artifacts
- .pytest_cache and test execution caches
- Virtual environment directories (.venv, venv, env)
- Temporary session files, secrets, debug logs (.log, .tmp), and caches
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_ZIP = PROJECT_ROOT / "NetCoop_AI_Submission.zip"

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".venv",
    "venv",
    "env",
    ".session_store",
    ".idea",
    ".vscode",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".gemini"
}

EXCLUDED_FILES = {
    "NetCoop_AI_Submission.zip",
    "netcoop_ai_demo.mp4",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}

EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
    ".tmp",
    ".swp",
    ".bak",
    ".tsbuildinfo"
}


def should_exclude(file_path: Path) -> bool:
    rel = file_path.relative_to(PROJECT_ROOT)
    # Check directory parts
    for part in rel.parts:
        if part in EXCLUDED_DIRS:
            return True
    # Check exact filenames
    if file_path.name in EXCLUDED_FILES:
        return True
    # Exclude any .env secrets (preserve only .env.example)
    if (file_path.name.startswith(".env") or ".env." in file_path.name) and file_path.name != ".env.example":
        return True
    # Check extensions
    if file_path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True
    # Exclude legacy Next.js app directories
    if any(rel.parts[0] == d for d in ("app", "components", "lib", "prisma")):
        return True
    return False


def verify_submission_zip(zip_path: Path) -> Dict[str, Any]:
    """Programmatically verify archive integrity and certify exclusion of forbidden files."""
    print(f"\n--- PROGRAMMATIC SUBMISSION INTEGRITY AUDIT ---")
    if not zip_path.exists():
        raise FileNotFoundError(f"Target archive not found: {zip_path}")

    violations: List[str] = []
    total_uncompressed = 0
    total_files = 0

    with zipfile.ZipFile(zip_path, "r") as z:
        infolist = z.infolist()
        total_files = len(infolist)
        for info in infolist:
            name = info.filename.replace("\\", "/")
            total_uncompressed += info.file_size
            path_parts = name.split("/")

            # Check forbidden directory parts
            for part in path_parts:
                if part in EXCLUDED_DIRS:
                    violations.append(f"Forbidden directory in '{name}' ({part})")

            # Check forbidden extensions
            ext = Path(name).suffix.lower()
            if ext in EXCLUDED_EXTENSIONS:
                violations.append(f"Forbidden extension '{ext}' in '{name}'")

            # Check secret .env files
            basename = path_parts[-1]
            if (basename.startswith(".env") or ".env." in basename) and basename != ".env.example":
                violations.append(f"Forbidden environment secret file '{name}'")

            if basename in EXCLUDED_FILES:
                violations.append(f"Forbidden file '{basename}' in '{name}'")

    compressed_size = zip_path.stat().st_size
    ratio = (1.0 - (compressed_size / total_uncompressed)) * 100 if total_uncompressed > 0 else 0.0

    print(f"  Verified Files in Archive : {total_files}")
    print(f"  Total Uncompressed Size   : {total_uncompressed / (1024 * 1024):.2f} MB")
    print(f"  Compressed Archive Size   : {compressed_size / (1024 * 1024):.2f} MB")
    print(f"  Overall Compression Ratio : {ratio:.1f}%")
    print(f"  Exclusion Rule Violations : {len(violations)}")

    if violations:
        for v in violations[:10]:
            print(f"    [VIOLATION] {v}")
        raise ValueError(f"Archive verification failed with {len(violations)} rule violations!")

    print(f"  Audit Certification Status: VERIFIED CLEAN (Zero forbidden files)")
    return {
        "total_files": total_files,
        "uncompressed_bytes": total_uncompressed,
        "compressed_bytes": compressed_size,
        "violations_count": 0,
        "status": "VERIFIED_CLEAN"
    }


def build_submission_zip() -> Dict[str, Any]:
    print(f"\n=======================================================")
    print(f" NETCOOP AI — SUBMISSION PACKAGING HARNESS")
    print(f"=======================================================\n")
    print(f"Project Root: {PROJECT_ROOT}")
    print(f"Target Archive: {OUTPUT_ZIP.name}")

    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    included_count = 0
    with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and d not in ("app", "components", "lib", "prisma")]
            for file in files:
                full_path = Path(root) / file
                if not should_exclude(full_path):
                    arcname = full_path.relative_to(PROJECT_ROOT)
                    zipf.write(full_path, arcname=arcname)
                    included_count += 1

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"\n[OK] Package created successfully!")
    print(f"Total files packaged: {included_count}")
    print(f"Archive file size:   {size_mb:.2f} MB")
    print(f"Saved to:            {OUTPUT_ZIP}")

    # Run programmatic verification
    audit_result = verify_submission_zip(OUTPUT_ZIP)
    return audit_result


if __name__ == "__main__":
    build_submission_zip()
