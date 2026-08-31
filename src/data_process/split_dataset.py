"""Create a reproducible 70/30 train-test split for pressure data files."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from sklearn.model_selection import train_test_split


def collect_samples(input_dir: Path) -> list[Path]:
    """Collect files from class folders or from a flat input directory."""
    return sorted(path for path in input_dir.rglob("*") if path.is_file())


def split_dataset(
    input_dir: Path,
    output_dir: Path,
    test_size: float = 0.3,
    random_state: int = 42,
) -> dict[str, list[str]]:
    samples = collect_samples(input_dir)
    if not samples:
        raise ValueError(f"No data files found in {input_dir}")

    train_files, test_files = train_test_split(
        samples,
        test_size=test_size,
        random_state=random_state,
        shuffle=True,
    )

    manifest = {
        "train": [str(path.relative_to(input_dir)) for path in train_files],
        "test": [str(path.relative_to(input_dir)) for path in test_files],
    }

    for split_name, paths in (("train", train_files), ("test", test_files)):
        for source in paths:
            target = output_dir / split_name / source.relative_to(input_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "split_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Split pressure data into train/test folders.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--test-size", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    manifest = split_dataset(args.input_dir, args.output_dir, args.test_size, args.seed)
    print(f"Created split: {len(manifest['train'])} train, {len(manifest['test'])} test")


if __name__ == "__main__":
    main()
