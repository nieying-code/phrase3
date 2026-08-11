"""Design-stage entry point for the isolated Phase 6 M1 namespace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .phase6_m1 import (
    M1_EXECUTION_READY_STATUS,
    load_m1_config,
    m1_fingerprints,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="configs/phase6_m1_procurement_cap.yaml",
    )
    parser.add_argument(
        "--runner-config",
        default="configs/phase6_m1_runner.yaml",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    config_path = project_root / args.config
    runner_config_path = project_root / args.runner_config
    config = load_m1_config(config_path)
    fingerprints = m1_fingerprints(
        project_root=project_root,
        config_path=config_path,
        runner_config_path=runner_config_path,
    )
    if not args.validate_only:
        raise RuntimeError(
            "M1 execution is disabled in the design PR; use --validate-only. "
            f"A later reviewed revision must set status to "
            f"{M1_EXECUTION_READY_STATUS!r} before development execution."
        )
    print(
        json.dumps(
            {
                "protocol_id": config["protocol_id"],
                "status": config["status"],
                "runner_namespace": config["runner_namespace"],
                "output_root": config["output_root"],
                "development_configuration_count": config[
                    "development_preregistration"
                ]["configuration_count"],
                "fingerprints": fingerprints,
                "execution_performed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
