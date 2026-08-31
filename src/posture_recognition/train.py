"""Training entry point for posture recognition models."""

from __future__ import annotations

import argparse
from pathlib import Path


def train(data_dir: Path, model_dir: Path, algorithm: str) -> None:
    """Placeholder for posture recognition training.

    Implement at least two algorithms here or dispatch to dedicated modules.
    """
    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"[posture] training algorithm={algorithm} data_dir={data_dir} model_dir={model_dir}")
    print("[posture] TODO: load pressure matrices, augment data, train model, save artifact.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a posture recognition model.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed/train"))
    parser.add_argument("--model-dir", type=Path, default=Path("src/posture_recognition/models"))
    parser.add_argument(
        "--algorithm",
        choices=("svm", "random_forest", "cnn"),
        default="svm",
        help="Algorithm to train.",
    )
    args = parser.parse_args()
    train(args.data_dir, args.model_dir, args.algorithm)


if __name__ == "__main__":
    main()
