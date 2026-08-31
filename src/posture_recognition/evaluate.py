"""Evaluation entry point for posture recognition models."""

from __future__ import annotations

import argparse
from pathlib import Path


def evaluate(data_dir: Path, model_path: Path) -> None:
    """Placeholder for accuracy, precision, recall, and F1 evaluation."""
    print(f"[posture] evaluating model={model_path} data_dir={data_dir}")
    print("[posture] TODO: compute accuracy, precision, recall, F1, and confusion matrix.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a posture recognition model.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed/test"))
    parser.add_argument("--model-path", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.data_dir, args.model_path)


if __name__ == "__main__":
    main()
