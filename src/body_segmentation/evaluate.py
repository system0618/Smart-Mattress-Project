"""Evaluation entry point for body segmentation models."""

from __future__ import annotations

import argparse
from pathlib import Path


def evaluate(data_dir: Path, model_path: Path) -> None:
    print(f"[segmentation] evaluating model={model_path} data_dir={data_dir}")
    print("[segmentation] TODO: compute validation accuracy and new-user generalization accuracy.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a body segmentation model.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed/test"))
    parser.add_argument("--model-path", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.data_dir, args.model_path)


if __name__ == "__main__":
    main()
