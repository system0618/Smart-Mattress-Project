"""Paper-style PolishNetU training with heatmap and PAF supervision.

This module implements the three trainable stages described in Davoodnia et al.:

1. re-train a multi-stage image pose estimator on annotated pressure maps;
2. freeze that estimator and train PolishNetU with pose and pixel losses;
3. jointly fine-tune PolishNetU and the pose estimator.

Unlike the earlier pressure-domain baseline, polished images are not trained
against a hand-crafted brightened target and no spatial gate is used at export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import h5py
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

from .enhance import PAF_LIMBS, build_pose_targets
from .visualize_enhancement import save_comparison


class AnnotatedPoseDataset(Dataset):
    """Lazily read Viridis pressure images and their real 14-joint labels."""

    def __init__(self, path: str | Path, max_samples: int | None = None) -> None:
        self.path = str(path)
        self._file: h5py.File | None = None
        with h5py.File(self.path, "r") as file:
            for key in ("input_images", "target_images", "body_mask", "joints", "joint_valid"):
                if key not in file:
                    raise KeyError(f"{self.path} lacks required dataset '{key}'")
            available = len(file["input_images"])
        self.length = min(available, max_samples) if max_samples else available

    def __len__(self) -> int:
        return self.length

    def _open(self) -> h5py.File:
        if self._file is None:
            self._file = h5py.File(self.path, "r")
        return self._file

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        file = self._open()
        image = np.asarray(file["input_images"][index], dtype=np.float32)
        if image.ndim != 3 or image.shape[-1] != 3:
            raise ValueError(f"Expected HWC RGB image, got {image.shape}")
        image_tensor = torch.from_numpy(image.copy()).permute(2, 0, 1) * 2.0 - 1.0
        target = np.asarray(file["target_images"][index], dtype=np.float32)
        target_tensor = torch.from_numpy(target.copy()).permute(2, 0, 1) * 2.0 - 1.0
        body_mask = torch.from_numpy(np.asarray(file["body_mask"][index], dtype=np.float32).copy())
        joints = torch.from_numpy(np.asarray(file["joints"][index], dtype=np.float32))
        valid = torch.from_numpy(np.asarray(file["joint_valid"][index], dtype=np.float32))
        return image_tensor, target_tensor, body_mask, joints, valid

    def __del__(self) -> None:
        if self._file is not None:
            self._file.close()


class PressureImageDataset(Dataset):
    """Read only RGB pressure images for deployment-time enhancement."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._file: h5py.File | None = None
        with h5py.File(self.path, "r") as file:
            self.key = "input_images" if "input_images" in file else "images"
            if self.key not in file:
                raise KeyError(f"{self.path} needs an 'input_images' or 'images' dataset")
            self.length = len(file[self.key])

    def __len__(self) -> int:
        return self.length

    def _open(self) -> h5py.File:
        if self._file is None:
            self._file = h5py.File(self.path, "r")
        return self._file

    def __getitem__(self, index: int) -> torch.Tensor:
        raw_image = np.asarray(self._open()[self.key][index])
        if raw_image.ndim != 3 or raw_image.shape[-1] != 3:
            raise ValueError(f"Expected HWC RGB image, got {raw_image.shape}")
        needs_uint8_scale = np.issubdtype(raw_image.dtype, np.integer)
        image = raw_image.astype(np.float32, copy=True)
        if needs_uint8_scale or float(image.max(initial=0.0)) > 1.0:
            image /= 255.0
        return torch.from_numpy(image).permute(2, 0, 1) * 2.0 - 1.0

    def __del__(self) -> None:
        if self._file is not None:
            self._file.close()


class _EncoderBlock(nn.Module):
    def __init__(self, channels_in: int, channels_out: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(channels_in, channels_out, 3, stride=2, padding=1),
            nn.BatchNorm2d(channels_out),
            nn.LeakyReLU(0.2, inplace=True),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.block(value)


class _DecoderBlock(nn.Module):
    """UpSample -> convolution -> BatchNorm -> LeakyReLU."""

    def __init__(self, channels_in: int, channels_out: int) -> None:
        super().__init__()
        self.convolution = nn.Conv2d(channels_in, channels_out, 3, padding=1)
        self.normalization = nn.BatchNorm2d(channels_out)
        self.activation = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, value: torch.Tensor, size: tuple[int, int]) -> torch.Tensor:
        value = nn.functional.interpolate(value, size=size, mode="nearest")
        return self.activation(self.normalization(self.convolution(value)))


class PaperPolishNetU(nn.Module):
    """Eight-level U-Net used only as the paper's image-space adapter."""

    def __init__(self, base_channels: int = 24) -> None:
        super().__init__()
        widths = [min(base_channels * 2**index, 384) for index in range(8)]
        self.encoder = nn.ModuleList(
            _EncoderBlock(3 if index == 0 else widths[index - 1], width)
            for index, width in enumerate(widths)
        )
        decoder_out = list(reversed(widths[:-1]))
        decoder_in: list[int] = [widths[-1]]
        for index in range(1, 7):
            decoder_in.append(decoder_out[index - 1] + widths[-1 - index])
        decoder_in.append(decoder_out[5] + widths[1])
        self.decoder = nn.ModuleList(
            _DecoderBlock(channels_in, channels_out)
            for channels_in, channels_out in zip(decoder_in, decoder_out)
        )
        self.output = nn.Conv2d(decoder_out[-1] + widths[0], 3, 3, padding=1)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        features: list[torch.Tensor] = []
        hidden = image
        for block in self.encoder:
            hidden = block(hidden)
            features.append(hidden)
        for block, skip in zip(self.decoder, reversed(features[:-1])):
            hidden = block(hidden, skip.shape[-2:])
            hidden = torch.cat((hidden, skip), dim=1)
        hidden = nn.functional.interpolate(hidden, size=image.shape[-2:], mode="nearest")
        # The paper uses tanh as the final activation and does not impose the
        # residual clamp used by the project's previous conservative baseline.
        return torch.tanh(self.output(hidden))


class MultiStagePoseEstimator(nn.Module):
    """Pretrained CMU OpenPose converted to the project's 14-joint convention."""

    HEATMAP_INDEX = (0, 1, 5, 2, 6, 3, 7, 4, 11, 8, 12, 9, 13, 10)
    # Each tuple is (OpenPose x channel, OpenPose y channel, direction sign).
    # The final channel pair is reassigned to the hip-to-hip connection while
    # the pose estimator is re-trained on pressure annotations.
    PAF_INDEX = (
        (28, 29, -1.0),
        (20, 21, 1.0), (22, 23, 1.0), (24, 25, 1.0),
        (12, 13, 1.0), (14, 15, 1.0), (16, 17, 1.0),
        (6, 7, 1.0), (8, 9, 1.0), (10, 11, 1.0),
        (0, 1, 1.0), (2, 3, 1.0), (4, 5, 1.0),
        (18, 19, 1.0),
    )

    def __init__(self, stages: int = 6) -> None:
        super().__init__()
        if stages != 6:
            raise ValueError("The supported pretrained OpenPose checkpoint has exactly 6 stages")
        try:
            from controlnet_aux.open_pose.model import bodypose_model
        except ImportError as error:
            raise ImportError("Install the OpenPose dependency with: pip install controlnet-aux") from error
        self.model = bodypose_model()
        self.stage_count = stages

    def initialize_pretrained(self) -> None:
        """Load converted COCO OpenPose weights, downloading them once if absent."""
        from huggingface_hub import hf_hub_download

        repository = "lllyasviel/ControlNet"
        filename = "annotator/ckpts/body_pose_model.pth"
        try:
            weight_path = hf_hub_download(repository, filename, local_files_only=True)
        except Exception:
            weight_path = hf_hub_download(repository, filename)
        source = torch.load(weight_path, map_location="cpu", weights_only=True)
        transferred = {
            model_name: source[".".join(model_name.split(".")[1:])]
            for model_name in self.model.state_dict()
        }
        self.model.load_state_dict(transferred)

    @classmethod
    def _select_outputs(
        cls,
        paf: torch.Tensor,
        heatmap: torch.Tensor,
        target_size: tuple[int, int],
    ) -> tuple[torch.Tensor, torch.Tensor]:
        selected_heatmap = heatmap[:, cls.HEATMAP_INDEX]
        paf_channels: list[torch.Tensor] = []
        for x_index, y_index, sign in cls.PAF_INDEX:
            paf_channels.extend((paf[:, x_index:x_index + 1] * sign, paf[:, y_index:y_index + 1] * sign))
        selected_paf = torch.cat(paf_channels, dim=1)
        if selected_heatmap.shape[-2:] != target_size:
            selected_heatmap = nn.functional.interpolate(
                selected_heatmap, target_size, mode="bilinear", align_corners=False
            )
            selected_paf = nn.functional.interpolate(
                selected_paf, target_size, mode="bilinear", align_corners=False
            )
        return selected_heatmap, selected_paf

    def forward(self, image: torch.Tensor) -> list[tuple[torch.Tensor, torch.Tensor]]:
        target_size = image.shape[-2:]
        # OpenPose has output stride 8; this yields one belief-map cell per
        # original pressure sensor.
        resized = nn.functional.interpolate(image, scale_factor=8.0, mode="bilinear", align_corners=False)
        # Match the original converted Caffe model's BGR preprocessing.
        bgr = resized[:, (2, 1, 0)] * (127.5 / 256.0) - (0.5 / 256.0)
        features = self.model.model0(bgr)
        outputs: list[tuple[torch.Tensor, torch.Tensor]] = []
        paf = self.model.model1_1(features)
        heatmap = self.model.model1_2(features)
        outputs.append(self._select_outputs(paf, heatmap, target_size))
        for stage_index in range(2, 7):
            stage_input = torch.cat((paf, heatmap, features), dim=1)
            paf = getattr(self.model, f"model{stage_index}_1")(stage_input)
            heatmap = getattr(self.model, f"model{stage_index}_2")(stage_input)
            outputs.append(self._select_outputs(paf, heatmap, target_size))
        return outputs


def _visibility_masks(valid: torch.Tensor, height: int, width: int) -> tuple[torch.Tensor, torch.Tensor]:
    joint_mask = valid.bool()[:, :, None, None].expand(-1, -1, height, width)
    limb_valid = torch.stack(
        [valid[:, start].bool() & valid[:, end].bool() for start, end in PAF_LIMBS], dim=1
    )
    paf_mask = limb_valid.repeat_interleave(2, dim=1)[:, :, None, None].expand(-1, -1, height, width)
    return joint_mask, paf_mask


def _masked_mse(prediction: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    # Keep the reduction in FP32. With batch_size=16 the visibility-mask count
    # exceeds float16's finite range (65504), which would otherwise turn the
    # denominator into infinity and silently make the loss zero.
    weighted = (prediction.float() - target.float()).square() * mask.float()
    return weighted.sum() / mask.sum().clamp_min(1).float()


def pose_objective(
    stage_outputs: Iterable[tuple[torch.Tensor, torch.Tensor]],
    joints: torch.Tensor,
    valid: torch.Tensor,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    outputs = list(stage_outputs)
    height, width = outputs[-1][0].shape[-2:]
    heatmap_target, paf_target = build_pose_targets(
        joints, valid, height, width, sigma=1.5, paf_thickness=1.25
    )
    joint_mask, paf_mask = _visibility_masks(valid, height, width)
    heatmap_losses = [_masked_mse(heatmap, heatmap_target, joint_mask) for heatmap, _ in outputs]
    paf_losses = [_masked_mse(paf, paf_target, paf_mask) for _, paf in outputs]
    heatmap_loss = torch.stack(heatmap_losses).mean()
    paf_loss = torch.stack(paf_losses).mean()
    return heatmap_loss + paf_loss, {"heatmap": heatmap_loss.detach(), "paf": paf_loss.detach()}


def paper_objective(
    polished: torch.Tensor,
    target: torch.Tensor,
    body_mask: torch.Tensor,
    pose_outputs: Iterable[tuple[torch.Tensor, torch.Tensor]],
    joints: torch.Tensor,
    valid: torch.Tensor,
    pixel_weight: float,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    pose_loss, parts = pose_objective(pose_outputs, joints, valid)
    error = (polished - target).square().mean(dim=1, keepdim=True)
    region = body_mask[:, None] if body_mask.ndim == 3 else body_mask
    pixel_loss = ((1.0 + 2.0 * region.clamp(0.0, 1.0)) * error).mean()
    total = pose_loss + pixel_weight * pixel_loss
    parts["pixel"] = pixel_loss.detach()
    return total, parts


def _loader(dataset: Dataset, batch_size: int, shuffle: bool, device: torch.device) -> DataLoader:
    return DataLoader(
        dataset, batch_size=batch_size, shuffle=shuffle, num_workers=0,
        pin_memory=device.type == "cuda", drop_last=shuffle and len(dataset) >= batch_size,
    )


def _decay_learning_rate(optimizer: torch.optim.Optimizer, step: int, initial_lr: float) -> None:
    # Exact paper schedule: multiply by 0.95 every 1000 updates. A small floor
    # prevents underflow if this code is later used with a much larger dataset.
    learning_rate = max(1e-6, initial_lr * 0.95 ** (step // 1000))
    for group in optimizer.param_groups:
        group["lr"] = learning_rate


def _save(path: str | Path, **values: object) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    torch.save(values, destination)
    print(f"Checkpoint saved to {destination}")


def train_pose(
    train_h5: str | Path,
    checkpoint: str | Path,
    epochs: int = 40,
    batch_size: int = 16,
    learning_rate: float = 1e-3,
    max_samples: int | None = None,
) -> None:
    """Re-train an image-pretrained pose estimator on pressure annotations."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dataset = AnnotatedPoseDataset(train_h5, max_samples)
    loader = _loader(dataset, batch_size, True, device)
    model = MultiStagePoseEstimator().to(device)
    model.initialize_pretrained()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    step = 0
    print(f"Pose-estimator retraining on {device}: {len(dataset)} samples")
    for epoch in range(epochs):
        model.train()
        running = 0.0
        for image, _, _, joints, valid in tqdm(loader, desc=f"pose {epoch + 1}/{epochs}", unit="batch"):
            image, joints, valid = image.to(device), joints.to(device), valid.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda", dtype=torch.float16, enabled=device.type == "cuda"):
                loss, _ = pose_objective(model(image), joints, valid)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            step += 1
            _decay_learning_rate(optimizer, step, learning_rate)
            running += float(loss.detach())
        print(f"pose epoch {epoch + 1}/{epochs} loss={running / len(loader):.6f} lr={optimizer.param_groups[0]['lr']:.2e}")
    _save(
        checkpoint, pose_state_dict=model.state_dict(), optimizer_state_dict=optimizer.state_dict(), epoch=epochs,
        stages=model.stage_count, method="retrained_pretrained_openpose",
    )


def _load_pose(path: str | Path, device: torch.device) -> MultiStagePoseEstimator:
    state = torch.load(path, map_location="cpu", weights_only=False)
    model = MultiStagePoseEstimator(stages=int(state.get("stages", 7))).to(device)
    model.load_state_dict(state["pose_state_dict"])
    return model


def train_polish(
    train_h5: str | Path,
    pose_checkpoint: str | Path | None,
    checkpoint: str | Path,
    epochs: int = 40,
    batch_size: int = 16,
    base_channels: int = 24,
    learning_rate: float = 1e-3,
    max_samples: int | None = None,
) -> None:
    """Train PolishNetU while the natural-image OpenPose stays frozen."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dataset = AnnotatedPoseDataset(train_h5, max_samples)
    loader = _loader(dataset, batch_size, True, device)
    if pose_checkpoint is None:
        pose = MultiStagePoseEstimator().to(device)
        pose.initialize_pretrained()
        pose_source = "pretrained_openpose_coco"
    else:
        # This option supports ablation experiments, but the paper-style image
        # adaptation stage starts from the natural-image model above.
        pose = _load_pose(pose_checkpoint, device)
        pose_source = str(pose_checkpoint)
    pose.eval()
    pose.requires_grad_(False)
    polish = PaperPolishNetU(base_channels).to(device)
    optimizer = torch.optim.Adam(polish.parameters(), lr=learning_rate)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    step = 0
    print(f"Frozen-pose PolishNetU training on {device}: {len(dataset)} samples")
    for epoch in range(epochs):
        polish.train()
        pixel_weight = 1.0 + (0.01 - 1.0) * epoch / max(epochs - 1, 1)
        running = 0.0
        for image, target, body_mask, joints, valid in tqdm(loader, desc=f"polish {epoch + 1}/{epochs}", unit="batch"):
            image, target, body_mask = image.to(device), target.to(device), body_mask.to(device)
            joints, valid = joints.to(device), valid.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda", dtype=torch.float16, enabled=device.type == "cuda"):
                polished = polish(image)
                loss, _ = paper_objective(polished, target, body_mask, pose(polished), joints, valid, pixel_weight)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            step += 1
            _decay_learning_rate(optimizer, step, learning_rate)
            running += float(loss.detach())
        print(
            f"polish epoch {epoch + 1}/{epochs} loss={running / len(loader):.6f} "
            f"pixel_weight={pixel_weight:.3f} lr={optimizer.param_groups[0]['lr']:.2e}"
        )
    _save(
        checkpoint, polish_state_dict=polish.state_dict(), pose_state_dict=pose.state_dict(),
        optimizer_state_dict=optimizer.state_dict(), epoch=epochs,
        stages=pose.stage_count, base_channels=base_channels,
        pose_source=pose_source, method="frozen_pretrained_pose_plus_polishnetu",
    )


def finetune(
    train_h5: str | Path,
    input_checkpoint: str | Path,
    checkpoint: str | Path,
    epochs: int = 40,
    batch_size: int = 16,
    learning_rate: float = 1e-4,
    max_samples: int | None = None,
) -> None:
    """Jointly fine-tune PolishNetU and the pose estimator (paper's best setup)."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(input_checkpoint, map_location="cpu", weights_only=False)
    base_channels = int(state.get("base_channels", 24))
    polish = PaperPolishNetU(base_channels).to(device)
    pose = MultiStagePoseEstimator(stages=int(state.get("stages", 7))).to(device)
    polish.load_state_dict(state["polish_state_dict"])
    pose.load_state_dict(state["pose_state_dict"])
    dataset = AnnotatedPoseDataset(train_h5, max_samples)
    loader = _loader(dataset, batch_size, True, device)
    optimizer = torch.optim.Adam(list(polish.parameters()) + list(pose.parameters()), lr=learning_rate)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    step = 0
    print(f"Joint PolishNetU/pose fine-tuning on {device}: {len(dataset)} samples")
    for epoch in range(epochs):
        polish.train(); pose.train()
        pixel_weight = 1.0 + (0.01 - 1.0) * epoch / max(epochs - 1, 1)
        running = 0.0
        for image, target, body_mask, joints, valid in tqdm(loader, desc=f"joint {epoch + 1}/{epochs}", unit="batch"):
            image, target, body_mask = image.to(device), target.to(device), body_mask.to(device)
            joints, valid = joints.to(device), valid.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda", dtype=torch.float16, enabled=device.type == "cuda"):
                polished = polish(image)
                loss, _ = paper_objective(polished, target, body_mask, pose(polished), joints, valid, pixel_weight)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            step += 1
            _decay_learning_rate(optimizer, step, learning_rate)
            running += float(loss.detach())
        print(
            f"joint epoch {epoch + 1}/{epochs} loss={running / len(loader):.6f} "
            f"pixel_weight={pixel_weight:.3f} lr={optimizer.param_groups[0]['lr']:.2e}"
        )
    _save(
        checkpoint, polish_state_dict=polish.state_dict(), pose_state_dict=pose.state_dict(),
        optimizer_state_dict=optimizer.state_dict(), epoch=epochs,
        stages=pose.stage_count, base_channels=base_channels,
        method="retrained_pose_plus_finetuned_polishnetu",
    )


def _flip_test_heatmaps(pose: MultiStagePoseEstimator, image: torch.Tensor) -> torch.Tensor:
    """Apply the paper's horizontal flip test and 3x3 Gaussian smoothing."""
    direct = pose(image)[-1][0]
    mirrored = pose(torch.flip(image, dims=(-1,)))[-1][0]
    # Swap left/right anatomical channels after restoring image orientation.
    swap = (0, 1, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10, 13, 12)
    mirrored = torch.flip(mirrored[:, swap], dims=(-1,))
    averaged = (direct + mirrored) * 0.5
    kernel = averaged.new_tensor(((1.0, 2.0, 1.0), (2.0, 4.0, 2.0), (1.0, 2.0, 1.0))) / 16.0
    kernel = kernel[None, None].expand(14, 1, 3, 3)
    return nn.functional.conv2d(averaged, kernel, padding=1, groups=14)


@torch.inference_mode()
def evaluate(
    test_h5: str | Path,
    checkpoint: str | Path,
    output_json: str | Path,
    batch_size: int = 16,
    max_samples: int | None = None,
) -> dict[str, dict[str, float]]:
    """Report MPJPE and PCK@5% before and after PolishNetU."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    polish = PaperPolishNetU(int(state.get("base_channels", 24))).to(device)
    pose = MultiStagePoseEstimator(stages=int(state.get("stages", 6))).to(device)
    polish.load_state_dict(state["polish_state_dict"])
    pose.load_state_dict(state["pose_state_dict"])
    polish.eval(); pose.eval()
    dataset = AnnotatedPoseDataset(test_h5, max_samples)
    loader = _loader(dataset, batch_size, False, device)
    totals = {
        "raw": {"distance": 0.0, "correct": 0.0, "count": 0.0},
        "polished": {"distance": 0.0, "correct": 0.0, "count": 0.0},
    }
    for image, _, _, joints, valid in tqdm(loader, desc="paper evaluation", unit="batch"):
        image, joints, valid = image.to(device), joints.to(device), valid.to(device).bool()
        for name, current in (("raw", image), ("polished", polish(image))):
            heatmap = _flip_test_heatmaps(pose, current)
            flat = heatmap.flatten(2).argmax(dim=-1)
            predicted = torch.stack((flat % heatmap.shape[-1], flat // heatmap.shape[-1]), dim=-1).to(joints.dtype)
            distance = torch.linalg.vector_norm(predicted - joints, dim=-1)
            # The paper normalizes its 5% threshold using left shoulder to
            # right hip torso length (indices 2 and 9 in this dataset).
            torso = torch.linalg.vector_norm(joints[:, 2] - joints[:, 9], dim=-1)
            torso_valid = valid[:, 2] & valid[:, 9] & (torso > 0)
            fallback = math.sqrt(image.shape[-2] ** 2 + image.shape[-1] ** 2)
            threshold = torch.where(torso_valid, torso, torso.new_full(torso.shape, fallback)) * 0.05
            selected = distance.masked_select(valid)
            totals[name]["distance"] += float(selected.sum())
            totals[name]["correct"] += float(((distance <= threshold[:, None]) & valid).sum())
            totals[name]["count"] += float(valid.sum())
    report = {
        name: {
            "mpjpe_pixels": values["distance"] / max(values["count"], 1.0),
            "pck_at_5_percent": values["correct"] / max(values["count"], 1.0),
            "visible_joints": int(values["count"]),
        }
        for name, values in totals.items()
    }
    destination = Path(output_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_model(
    input_checkpoint: str | Path,
    output_checkpoint: str | Path,
    manifest_path: str | Path | None = None,
) -> Path:
    """Create a compact inference artifact without OpenPose or optimizer state."""
    source = Path(input_checkpoint)
    state = torch.load(source, map_location="cpu", weights_only=False)
    if "polish_state_dict" not in state:
        raise KeyError(f"{source} is not a PaperPolishNetU training checkpoint")
    destination = Path(output_checkpoint)
    destination.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "artifact_type": "pressure_enhancement_inference",
        "format_version": 1,
        "model": "PaperPolishNetU",
        "base_channels": int(state.get("base_channels", 24)),
        "input": {"layout": "NHWC", "shape": [24, 44, 3], "encoding": "Viridis RGB in [0, 1]"},
        "output": {"layout": "NHWC", "shape": [24, 44, 3], "encoding": "uint8 Viridis RGB"},
        "source_training_checkpoint": source.name,
        "training_epoch": int(state.get("epoch", 0)),
        "method": str(state.get("method", "paper_style_polishnetu")),
        "polish_state_dict": state["polish_state_dict"],
    }
    torch.save(artifact, destination)
    manifest_destination = (
        Path(manifest_path)
        if manifest_path is not None
        else destination.with_suffix(".manifest.json")
    )
    manifest_destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {key: value for key, value in artifact.items() if key != "polish_state_dict"}
    manifest.update({"artifact_file": destination.name, "sha256": _sha256(destination), "bytes": destination.stat().st_size})
    manifest_destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Inference model saved to {destination}")
    print(f"Model manifest saved to {manifest_destination}")
    return destination


@torch.inference_mode()
def export(
    input_h5: str | Path,
    checkpoint: str | Path,
    output_h5: str | Path,
    comparison_output: str | Path,
    batch_size: int = 64,
) -> None:
    """Export un-gated, un-amplified PolishNetU images and a comparison figure."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model = PaperPolishNetU(int(state.get("base_channels", 24))).to(device)
    model.load_state_dict(state["polish_state_dict"])
    model.eval()
    dataset = PressureImageDataset(input_h5)
    loader = _loader(dataset, batch_size, False, device)
    destination = Path(output_h5)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(input_h5, "r") as source, h5py.File(destination, "w") as output:
        input_key = "input_images" if "input_images" in source else "images"
        shape = source[input_key].shape
        images = output.create_dataset(
            "images", shape=shape, dtype=np.uint8,
            chunks=(min(batch_size, shape[0]), *shape[1:]), compression="gzip",
        )
        offset = 0
        for batch in tqdm(loader, desc="export paper enhancement", unit="batch"):
            prediction = model(batch.to(device))
            rgb = ((prediction + 1.0) * 127.5).clamp(0, 255).byte().permute(0, 2, 3, 1).cpu().numpy()
            images[offset:offset + len(rgb)] = rgb
            offset += len(rgb)
        output.attrs["method"] = str(state.get("method", "paper_style_polishnetu"))
        output.attrs["postprocessing"] = "none"
        output.attrs["source_h5"] = str(input_h5)
    save_comparison(
        input_h5,
        destination,
        comparison_output,
        count=2,
        selection="body-focused",
        show_target=False,
    )
    print(f"Enhanced images saved to {destination}")
    print(f"Comparison saved to {comparison_output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper-style PolishNetU/OpenPose training pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pose_parser = subparsers.add_parser("train-pose", help="re-train the multi-stage pose estimator")
    pose_parser.add_argument("--train-h5", required=True)
    pose_parser.add_argument("--checkpoint", default="checkpoints/paper_pose_retrained.pt")

    polish_parser = subparsers.add_parser("train-polish", help="train PolishNetU with the pose estimator frozen")
    polish_parser.add_argument("--train-h5", required=True)
    polish_parser.add_argument(
        "--pose-checkpoint",
        help="optional pressure-retrained pose checkpoint for ablation; omit for the paper pipeline",
    )
    polish_parser.add_argument("--checkpoint", default="checkpoints/paper_polish_frozen_pose.pt")
    polish_parser.add_argument("--base-channels", type=int, default=24)

    joint_parser = subparsers.add_parser("finetune", help="jointly fine-tune the complete pipeline")
    joint_parser.add_argument("--train-h5", required=True)
    joint_parser.add_argument("--input-checkpoint", required=True)
    joint_parser.add_argument("--checkpoint", default="checkpoints/paper_polish_joint_final.pt")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--input-h5", required=True)
    export_parser.add_argument("--checkpoint", required=True)
    export_parser.add_argument("--output-h5", required=True)
    export_parser.add_argument(
        "--comparison-output",
        default="../压力增强对比图/论文流程/paper_final_comparison.png",
    )

    package_parser = subparsers.add_parser(
        "package-model",
        help="extract a compact PaperPolishNetU artifact for inference",
    )
    package_parser.add_argument("--input-checkpoint", required=True)
    package_parser.add_argument("--output", default="models/pressure_enhancement_v1.pt")
    package_parser.add_argument("--manifest", default="models/pressure_enhancement_v1.manifest.json")

    for current in (pose_parser, polish_parser, joint_parser):
        current.add_argument("--epochs", type=int, default=40)
        current.add_argument("--batch-size", type=int, default=16)
        current.add_argument("--learning-rate", type=float, default=None)
        current.add_argument("--max-samples", type=int)
    export_parser.add_argument("--batch-size", type=int, default=64)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--test-h5", required=True)
    evaluate_parser.add_argument("--checkpoint", required=True)
    evaluate_parser.add_argument("--output", default="reports/paper_pressure_enhancement_metrics.json")
    evaluate_parser.add_argument("--batch-size", type=int, default=16)
    evaluate_parser.add_argument("--max-samples", type=int)

    args = parser.parse_args()
    if args.command == "train-pose":
        train_pose(args.train_h5, args.checkpoint, args.epochs, args.batch_size, args.learning_rate or 1e-3, args.max_samples)
    elif args.command == "train-polish":
        train_polish(
            args.train_h5, args.pose_checkpoint, args.checkpoint, args.epochs,
            args.batch_size, args.base_channels, args.learning_rate or 1e-3, args.max_samples,
        )
    elif args.command == "finetune":
        finetune(
            args.train_h5, args.input_checkpoint, args.checkpoint, args.epochs,
            args.batch_size, args.learning_rate or 1e-4, args.max_samples,
        )
    elif args.command == "export":
        export(args.input_h5, args.checkpoint, args.output_h5, args.comparison_output, args.batch_size)
    elif args.command == "package-model":
        package_model(args.input_checkpoint, args.output, args.manifest)
    else:
        evaluate(args.test_h5, args.checkpoint, args.output, args.batch_size, args.max_samples)


if __name__ == "__main__":
    main()
