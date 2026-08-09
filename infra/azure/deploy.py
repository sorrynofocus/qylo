#!/usr/bin/env python3
# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.07.19
# Thin az CLI wrapper to (re)provision/preview the QnA-Chatbot's Azure OpenAI resource via Bicep.
# This resource provisions the Azure OpenAI model, including the necessary deployment and 
# configuration for the QnA-Chatbot.
#
# Purpose:
# Orchestrates `az login` (if needed) plus `az deployment sub validate/what-if/create`
# against main.bicep + main.bicepparam, so deployment is one command instead of manual
# az CLI steps or clicking through the Azure Portal.
#
# Usage examples (see infra/azure/README.md for granular details):
#
# Check the template/parameters are well-formed and would be accepted (safe, no changes):
# python deploy.py --location westus --validate
#
# Preview exactly what would change without applying it (safe, no changes):
# python deploy.py --location westus --dry-run
#
# Apply for real:
# python deploy.py --location westus
#
# Sign into a non-default Azure AD tenant first:
# python deploy.py --location westus --tenant <tenant-id> --dry-run
#
# Note: a Modules (removable) sub directory may exist for reusable Bicep modules referenced by main.bicep. 
# This allows for modular and maintainable Bicep code, keeping the main template clean and focused on the overall deployment structure.
""""""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

INFRA_DIR = Path(__file__).parent
TEMPLATE = INFRA_DIR / "main.bicep"
PARAMS = INFRA_DIR / "main.bicepparam"


def run(args: list[str]) -> None:
    print(f"$ {' '.join(args)}")

    result = subprocess.run(args, check=False)

    if result.returncode != 0:
        sys.exit(result.returncode)


def is_az_logged_in(az: str, tenant: str | None) -> None:
    if subprocess.run([az, "account", "show", "--only-show-errors"], capture_output=True).returncode == 0:
        return

    login_cmd = [az, "login"]

    if tenant:
        login_cmd += ["--tenant", tenant]

    run(login_cmd)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy or preview the Azure OpenAI Bicep template.")
    parser.add_argument("--location", required=True)
    parser.add_argument("--tenant", help="Azure AD tenant ID. Omit to use az's cached/default login.")

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview exactly what would change (az deployment what-if), without applying it.",
    )
    mode.add_argument(
        "--validate",
        action="store_true",
        help="Check the template/parameters are well-formed and would be accepted, without applying it.",
    )
    args = parser.parse_args()

    # Resolved lazily (not at import time) so --help works even without az on PATH.
    # subprocess needs the real resolved path, passing the bare string "az" fails with 
    # WinError 2, since CreateProcess doesn't apply the PATHEXT resolution a shell would.
    az = shutil.which("az")
    
    if az is None:
        sys.exit("az CLI not found on PATH. Install the Azure CLI and ensure `az` is available, then retry.")

    is_az_logged_in(az, args.tenant)

    action = "what-if" if args.dry_run else ("validate" if args.validate else "create")
    
    run(
        [
            az,
            "deployment",
            "sub",
            action,
            "--location",
            args.location,
            "--template-file",
            str(TEMPLATE),
            "--parameters",
            str(PARAMS),
        ]
    )
    
    # The equivalent raw az call this wrapper builds, for reference when debugging:
    # az deployment sub what-if --location westus --template-file infra\azure\main.bicep --parameters infra\azure\main.bicepparam


if __name__ == "__main__":
    main()
