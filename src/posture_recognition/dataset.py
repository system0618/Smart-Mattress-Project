"""Dataset loading and user-level splitting for sleep-posture recognition."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import numpy as np

POSTURE_NAMES = ("supine", "prone", "left_extended", "left_fetal", "right_extended", "right_fetal")
HEIGHT, WIDTH = 44, 24

@dataclass(frozen=True)
class PressureDataset:
    images: np.ndarray
    labels: np.ndarray
    users: np.ndarray

def load_json_dataset(json_path: Path, skip_frames: int = 3, min_mean_pressure: float = 1.0) -> PressureDataset:
    """Load labelled pressure frames from the supplied region dataset."""
    with json_path.open(encoding="utf-8") as stream:
        records = json.load(stream)
    images, labels, users = [], [], []
    frames_in_action: dict[tuple[str, int], int] = {}
    for record in records:
        label = int(record.get("sleep_pos", -1))
        if label not in range(len(POSTURE_NAMES)):
            continue
        values = np.asarray([float(value) for value in str(record.get("data", "")).split(",")], dtype=np.float32)
        if values.size != HEIGHT * WIDTH:
            continue
        user = str(record.get("people_name", record.get("people", "unknown")))
        key = (user, int(record.get("action", -1)))
        frame_index = frames_in_action.get(key, 0)
        frames_in_action[key] = frame_index + 1
        if frame_index < skip_frames:
            continue
        image = values.reshape(HEIGHT, WIDTH)
        if float(image.mean()) < min_mean_pressure:
            continue
        images.append(image); labels.append(label); users.append(user)
    if not images:
        raise ValueError(f"No labelled pressure frames found in {json_path}")
    return PressureDataset(np.stack(images).astype(np.float32), np.asarray(labels, dtype=np.int64), np.asarray(users))

def user_split(dataset: PressureDataset, train_ratio: float = 0.7, seed: int = 42):
    """Return train/test indices with no user overlap."""
    if not 0.0 < train_ratio < 1.0:
        raise ValueError("train_ratio must be between 0 and 1")
    unique_users = np.unique(dataset.users)
    if len(unique_users) < 2:
        raise ValueError("At least two users are required for a user-level split")
    shuffled = np.random.default_rng(seed).permutation(unique_users)
    cut = min(max(1, round(len(shuffled) * train_ratio)), len(shuffled) - 1)
    train_users, test_users = shuffled[:cut], shuffled[cut:]
    return (np.flatnonzero(np.isin(dataset.users, train_users)), np.flatnonzero(np.isin(dataset.users, test_users)), train_users.tolist(), test_users.tolist())
