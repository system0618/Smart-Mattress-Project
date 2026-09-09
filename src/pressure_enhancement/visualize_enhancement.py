"""Create side-by-side visual comparisons of original and enhanced HDF5 frames."""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import h5py
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _unit_float(images: np.ndarray) -> np.ndarray:
    """Convert either uint8 RGB or float RGB batches to float32 in [0, 1]."""
    values = np.asarray(images, dtype=np.float32)
    if np.issubdtype(np.asarray(images).dtype, np.integer) or float(values.max(initial=0.0)) > 1.0:
        values /= 255.0
    return np.clip(values, 0.0, 1.0)


def save_comparison(
    input_h5: str | Path,
    enhanced_h5: str | Path,
    output_path: str | Path,
    count: int = 5,
    selection: str = "representative",
    difference_scale: float = 16.0,
    selection_page: int = 0,
    show_target: bool = True,
) -> Path:
    """Save a compact original/enhanced comparison selected from HDF5 frames."""
    source_path = Path(input_h5)
    result_path = Path(enhanced_h5)
    destination = Path(output_path)
    if selection not in {"representative", "largest-difference", "body-focused"}:
        raise ValueError("selection must be 'representative', 'largest-difference', or 'body-focused'")
    if selection_page < 0:
        raise ValueError("selection_page must be non-negative")

    with h5py.File(source_path, "r") as source, h5py.File(result_path, "r") as enhanced_file:
        input_key = "input_images" if "input_images" in source else "images"
        original = source[input_key]
        clean_target = source["target_images"] if "target_images" in source else None
        enhanced_key = "images" if "images" in enhanced_file else "target_images"
        enhanced = enhanced_file[enhanced_key]
        enhanced_title = "PolishNetU output" if enhanced_key == "images" else "Strong enhancement target"
        if source_path.resolve() == result_path.resolve() and enhanced_key == "target_images":
            clean_target = None
        if original.shape != enhanced.shape:
            raise ValueError(f"Input/output shapes differ: {original.shape} vs {enhanced.shape}")
        total = len(original)
        if total == 0:
            raise ValueError("Cannot visualize an empty dataset")
        count = min(count, total)
        if selection == "representative":
            indices = np.linspace(0, total - 1, count, dtype=np.int64)
        else:
            sample_scores = np.empty(total, dtype=np.float32)
            body_mask = source.get("body_mask")
            for start in range(0, total, 128):
                stop = min(start + 128, total)
                before = _unit_float(original[start:stop])
                after = _unit_float(enhanced[start:stop])
                delta = np.abs(before - after)
                if body_mask is not None:
                    mask = np.asarray(body_mask[start:stop], dtype=np.float32)[..., None]
                    body_delta = (delta * mask).sum(axis=(1, 2, 3)) / mask.sum(axis=(1, 2, 3)).clip(min=1e-6)
                    if selection == "body-focused":
                        background = 1.0 - mask
                        background_delta = (delta * background).sum(axis=(1, 2, 3)) / background.sum(axis=(1, 2, 3)).clip(min=1e-6)
                        # Keep samples whose changes focus on the annotated
                        # human region instead of shifting the whole mattress.
                        sample_scores[start:stop] = body_delta - 0.5 * background_delta
                    else:
                        weights = 0.1 + 0.9 * mask
                        sample_scores[start:stop] = (delta * weights).sum(axis=(1, 2, 3)) / weights.sum(axis=(1, 2, 3))
                else:
                    sample_scores[start:stop] = delta.mean(axis=(1, 2, 3))

            # Prefer one strong example per user so adjacent frames from the
            # same recording do not fill the entire comparison sheet.
            users = source.get("user")
            ranked = np.argsort(sample_scores)[::-1]
            selected: list[int] = []
            if users is not None:
                user_values = np.asarray(users[:])
                seen_users: set[bytes] = set()
                for index in ranked:
                    index = int(index)
                    user = user_values[index]
                    if user in seen_users or not all(abs(index - previous) >= 30 for previous in selected):
                        continue
                    seen_users.add(user)
                    selected.append(index)
                    if len(selected) == count:
                        break
            if len(selected) < count:
                skip = selection_page * count
                for index in ranked:
                    if all(abs(int(index) - previous) >= 30 for previous in selected):
                        if skip:
                            skip -= 1
                            continue
                        selected.append(int(index))
                    if len(selected) == count:
                        break
            indices = np.asarray(selected[:count], dtype=np.int64)
        # h5py fancy indexing requires monotonically increasing indices; read
        # the handful of ranked frames individually to preserve score order.
        original_frames = _unit_float(np.stack([original[int(index)] for index in indices]))
        enhanced_frames = _unit_float(np.stack([enhanced[int(index)] for index in indices]))
        target_frames = (
            _unit_float(np.stack([clean_target[int(index)] for index in indices]))
            if clean_target is not None and show_target else None
        )

    columns = 4 if target_frames is not None else 3
    figure, axes = plt.subplots(count, columns, figsize=(5.8 * columns, 4.6 * count), squeeze=False)
    difference_maps = np.linalg.vector_norm(original_frames - enhanced_frames, axis=-1)
    difference_limit = max(float(np.quantile(difference_maps, 0.995)), 1e-4)
    for row, (index, before, after) in enumerate(zip(indices, original_frames, enhanced_frames)):
        axes[row, 0].imshow(before, interpolation="bicubic")
        axes[row, 0].set_title(f"Original pressure map (sample {index})", fontsize=13)
        axes[row, 1].imshow(after, interpolation="bicubic")
        axes[row, 1].set_title(enhanced_title, fontsize=13)
        if target_frames is not None:
            axes[row, 2].imshow(target_frames[row], interpolation="bicubic")
            axes[row, 2].set_title("Clean target", fontsize=13)
            change_axis = axes[row, 3]
        else:
            change_axis = axes[row, 2]
        change_axis.imshow(
            difference_maps[row], cmap="magma", vmin=0.0,
            vmax=difference_limit, interpolation="nearest",
        )
        change_axis.set_title("Enhancement magnitude", fontsize=13)
        for axis in axes[row]:
            axis.axis("off")
    figure.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(figure)
    print(f"Comparison image saved to: {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize PolishNetU enhancement results")
    parser.add_argument("input_h5")
    parser.add_argument("enhanced_h5")
    parser.add_argument("--output", required=True)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--selection", choices=("representative", "largest-difference", "body-focused"), default="representative")
    parser.add_argument("--difference-scale", type=float, default=16.0)
    parser.add_argument("--selection-page", type=int, default=0)
    parser.add_argument("--hide-target", action="store_true")
    args = parser.parse_args()
    save_comparison(
        args.input_h5, args.enhanced_h5, args.output, args.count, args.selection,
        args.difference_scale, args.selection_page, not args.hide_target
    )


if __name__ == "__main__":
    main()
