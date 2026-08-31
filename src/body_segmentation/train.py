"""Training entry point for body segmentation models."""

from __future__ import annotations

import argparse
from pathlib import Path


def train(data_dir: Path, model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"[segmentation] training data_dir={data_dir} model_dir={model_dir}")
    print("[segmentation] TODO: train segmentation model and save checkpoint.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a body segmentation model.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed/train"))
    parser.add_argument("--model-dir", type=Path, default=Path("src/body_segmentation/models"))
    args = parser.parse_args()
    train(args.data_dir, args.model_dir)


if __name__ == "__main__":
    main()
