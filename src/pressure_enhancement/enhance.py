"""PolishNetU pressure enhancement model and pose-supervised training loop."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import h5py
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


print("Initializing enhancement framework...")

# Joint order used by the annotated pressure dataset:
# head, neck, left/right shoulder, left/right elbow, left/right wrist,
# left/right hip, left/right knee, left/right ankle.
# Each anatomical limb produces an x and a y PAF channel.
PAF_LIMBS: tuple[tuple[int, int], ...] = (
    (0, 1),
    (1, 2), (2, 4), (4, 6),
    (1, 3), (3, 5), (5, 7),
    (1, 8), (8, 10), (10, 12),
    (1, 9), (9, 11), (11, 13),
    (8, 9),
)


class PressureH5Dataset(Dataset):
    """Lazy HDF5 reader supporting real joints, dense maps, or RGB-only data."""

    def __init__(self, path: str, target_path: Optional[str] = None, max_samples: Optional[int] = None):
        self.path = str(path)
        self.target_path = str(target_path) if target_path else None
        self._file: h5py.File | None = None
        print(f"Reading HDF5 structure: {self.path}")
        with h5py.File(self.path, "r") as file:
            if "input_images" in file and "target_images" in file:
                self.input_key = "input_images"
                self.target_key = "target_images"
            elif "images" in file:
                # Legacy datasets have no paired clean target and therefore
                # retain the original reconstruction behaviour.
                self.input_key = "images"
                self.target_key = "images"
            else:
                raise KeyError(f"HDF5 file has neither paired images nor an 'images' dataset: {self.path}")
            available = len(file[self.input_key])
            if len(file[self.target_key]) != available:
                raise ValueError("Input and target HDF5 datasets have different lengths")
            self.length = min(available, max_samples) if max_samples is not None else available
            if "joints" in file and "joint_valid" in file:
                self.pose_label_mode = "joints"
            elif "heatmap" in file and "paf" in file:
                self.pose_label_mode = "maps"
            else:
                self.pose_label_mode = "none"

    def __len__(self) -> int:
        return self.length

    def _open(self) -> h5py.File:
        if self._file is None:
            self._file = h5py.File(self.path, "r")
        return self._file

    @staticmethod
    def _to_tensor(image: np.ndarray) -> torch.Tensor:
        source_is_integer = np.issubdtype(image.dtype, np.integer)
        image = np.squeeze(np.asarray(image))
        if image.ndim == 2:
            image = np.repeat(image[..., None], 3, axis=-1)
        elif image.ndim == 3 and image.shape[-1] == 1:
            image = np.repeat(image, 3, axis=-1)
        if image.ndim != 3 or image.shape[-1] != 3:
            raise ValueError(f"Expected one RGB frame shaped (H, W, 3), got {image.shape}")
        image = image.astype(np.float32, copy=False)
        if source_is_integer or float(np.nanmax(image)) > 1.0:
            image = image / 255.0
        return torch.from_numpy(image.copy()).permute(2, 0, 1) * 2.0 - 1.0

    def __getitem__(self, index: int):
        file = self._open()
        image = self._to_tensor(np.asarray(file[self.input_key][index]))
        target = self._to_tensor(np.asarray(file[self.target_key][index]))
        if image.shape != target.shape:
            raise ValueError(f"Input/target tensor shapes differ: {tuple(image.shape)} vs {tuple(target.shape)}")
        if self.pose_label_mode == "joints":
            joints = torch.from_numpy(np.asarray(file["joints"][index], dtype=np.float32))
            valid = torch.from_numpy(np.asarray(file["joint_valid"][index], dtype=np.float32))
            return image, target, joints, valid
        if self.pose_label_mode == "maps":
            heatmap = torch.from_numpy(np.asarray(file["heatmap"][index], dtype=np.float32))
            paf = torch.from_numpy(np.asarray(file["paf"][index], dtype=np.float32))
            height, width = image.shape[-2:]
            if heatmap.shape[-2:] != (height, width) or paf.shape[-2:] != (height, width):
                raise ValueError(
                    "Pose-label dimensions do not match the pressure image. "
                    "Use the SLP converter or regenerate the legacy heatmap/paf labels."
                )
            return image, target, heatmap, paf
        height, width = image.shape[-2:]
        return image, target, torch.zeros((14, height, width)), torch.zeros((28, height, width))

    def __del__(self) -> None:
        if self._file is not None:
            self._file.close()


class _Down(nn.Module):
    def __init__(self, channels_in: int, channels_out: int):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(channels_in, channels_out, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(channels_out),
            nn.LeakyReLU(0.2, inplace=True),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.block(value)


class _Up(nn.Module):
    def __init__(self, channels_in: int, channels_out: int):
        super().__init__()
        self.block = nn.Sequential(
            nn.Upsample(scale_factor=2, mode="nearest"),
            nn.Conv2d(channels_in, channels_out, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(channels_out),
            nn.LeakyReLU(0.2, inplace=True),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.block(value)


class PolishNetU(nn.Module):
    """Eight-level PolishNetU with enhancement, heatmap, and PAF heads."""

    def __init__(
        self,
        in_channels: int = 3,
        out_channels: int = 3,
        base_channels: int = 8,
        residual_scale: float = 0.125,
    ):
        super().__init__()
        self.residual_scale = float(residual_scale)
        widths = [min(base_channels * 2 ** index, 512) for index in range(8)]
        self.encoder = nn.ModuleList(
            [_Down(in_channels if index == 0 else widths[index - 1], widths[index]) for index in range(8)]
        )
        decoder_inputs = [widths[7]] + [widths[7 - index] + widths[8 - index] for index in range(1, 8)]
        decoder_outputs = [widths[6 - index] for index in range(7)] + [base_channels]
        self.decoder = nn.ModuleList(
            [_Up(channels_in, channels_out) for channels_in, channels_out in zip(decoder_inputs, decoder_outputs)]
        )
        self.residual_head = nn.Sequential(
            nn.Conv2d(base_channels + widths[0] + in_channels, out_channels, kernel_size=3, padding=1),
            nn.Tanh(),
        )
        # Start from the identity mapping. The network then learns only the
        # pressure correction required to remove corruption, not the full RGB
        # image from scratch.
        nn.init.zeros_(self.residual_head[0].weight)
        nn.init.zeros_(self.residual_head[0].bias)
        self.pose_features = nn.Sequential(
            nn.Conv2d(out_channels, base_channels * 2, kernel_size=3, padding=1),
            nn.LeakyReLU(0.2, inplace=True),
        )
        self.heatmap_head = nn.Sequential(nn.Conv2d(base_channels * 2, 14, kernel_size=1), nn.Sigmoid())
        self.paf_head = nn.Sequential(nn.Conv2d(base_channels * 2, 28, kernel_size=1), nn.Tanh())

    def forward(self, value: torch.Tensor, return_pose: bool = False):
        skips: list[torch.Tensor] = []
        hidden = value
        for layer in self.encoder:
            hidden = layer(hidden)
            skips.append(hidden)
        for index, layer in enumerate(self.decoder):
            skip = skips[-1 - index]
            hidden = layer(hidden)
            hidden = nn.functional.interpolate(hidden, size=skip.shape[-2:], mode="nearest")
            hidden = torch.cat((hidden, skip), dim=1)
        hidden = nn.functional.interpolate(hidden, size=value.shape[-2:], mode="nearest")
        # Keep the correction small so pose/texture shortcuts cannot replace
        # the physical pressure pattern with high-frequency colour artifacts.
        residual = self.residual_head(torch.cat((hidden, value), dim=1))
        # The residual head uses tanh and the final tanh keeps the enhanced
        # image in [-1, 1] while preserving the identity when residual is zero.
        input_logits = torch.atanh(value.clamp(-0.999, 0.999))
        enhanced = torch.tanh(input_logits + self.residual_scale * residual)
        if not return_pose:
            return enhanced
        features = self.pose_features(enhanced)
        return enhanced, self.heatmap_head(features), self.paf_head(features)


def build_pose_targets(
    joints: torch.Tensor,
    valid: torch.Tensor,
    height: int,
    width: int,
    sigma: float = 2.0,
    paf_thickness: float = 2.0,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Build 14 Gaussian heatmaps and 28 PAF channels directly on the GPU."""
    if joints.ndim != 3 or joints.shape[1:] != (14, 2):
        raise ValueError(f"Expected joints shaped (B, 14, 2), got {tuple(joints.shape)}")
    if valid.shape != joints.shape[:2]:
        raise ValueError(f"Expected valid shaped {tuple(joints.shape[:2])}, got {tuple(valid.shape)}")

    safe_joints = torch.nan_to_num(joints)
    valid_mask = valid.bool() & torch.isfinite(joints).all(dim=-1)
    grid_y = torch.arange(height, device=joints.device, dtype=joints.dtype).view(1, 1, height, 1)
    grid_x = torch.arange(width, device=joints.device, dtype=joints.dtype).view(1, 1, 1, width)
    delta_x = grid_x - safe_joints[..., 0, None, None]
    delta_y = grid_y - safe_joints[..., 1, None, None]
    heatmap = torch.exp(-(delta_x.square() + delta_y.square()) / (2.0 * sigma * sigma))
    heatmap = heatmap * valid_mask[..., None, None].to(joints.dtype)

    paf = joints.new_zeros((joints.shape[0], len(PAF_LIMBS) * 2, height, width))
    for limb_index, (start_joint, end_joint) in enumerate(PAF_LIMBS):
        start = safe_joints[:, start_joint]
        end = safe_joints[:, end_joint]
        vector = end - start
        length = torch.linalg.vector_norm(vector, dim=1).clamp_min(1e-6)
        limb_valid = valid_mask[:, start_joint] & valid_mask[:, end_joint]
        unit_vector = vector / length[:, None]
        relative_x = grid_x[:, 0] - start[:, 0, None, None]
        relative_y = grid_y[:, 0] - start[:, 1, None, None]
        projection = relative_x * unit_vector[:, 0, None, None] + relative_y * unit_vector[:, 1, None, None]
        distance = torch.abs(relative_x * unit_vector[:, 1, None, None] - relative_y * unit_vector[:, 0, None, None])
        on_limb = (
            limb_valid[:, None, None]
            & (projection >= 0)
            & (projection <= length[:, None, None])
            & (distance <= paf_thickness)
        )
        paf[:, limb_index * 2] = torch.where(on_limb, unit_vector[:, 0, None, None], 0.0)
        paf[:, limb_index * 2 + 1] = torch.where(on_limb, unit_vector[:, 1, None, None], 0.0)
    return heatmap, paf


def composite_loss(
    enhanced: torch.Tensor,
    target: torch.Tensor,
    heatmap_pred: torch.Tensor | None = None,
    heatmap_target: torch.Tensor | None = None,
    paf_pred: torch.Tensor | None = None,
    paf_target: torch.Tensor | None = None,
    pixel_weight: float = 1.0,
    heatmap_weight: float = 0.1,
    paf_weight: float = 0.1,
    charbonnier_weight: float = 0.1,
    tv_weight: float = 0.05,
    weak_region_weight: float = 2.0,
    weak_gain_weight: float = 0.1,
    weak_gain: float = 0.05,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Compute pressure reconstruction loss plus optional pose supervision."""
    body_mask = None
    if heatmap_target is not None:
        body_mask = heatmap_target.amax(dim=1, keepdim=True).clamp(0.0, 1.0)
        if paf_target is not None:
            paf_mask = paf_target.square().sum(dim=1, keepdim=True).sqrt().clamp_max(1.0)
            body_mask = torch.maximum(body_mask, paf_mask)
        # Expand point-like joint targets to a coherent torso/limb region.
        body_mask = nn.functional.max_pool2d(body_mask, kernel_size=9, stride=1, padding=4)
    if body_mask is None:
        pixel = nn.functional.mse_loss(enhanced, target)
        weak_gain_loss = enhanced.new_zeros(())
    else:
        error = (enhanced - target).square().mean(dim=1, keepdim=True)
        pixel = ((1.0 + weak_region_weight * body_mask) * error).mean()
        target_level = (target + 1.0).mean(dim=1, keepdim=True) * 0.5
        output_level = (enhanced + 1.0).mean(dim=1, keepdim=True) * 0.5
        weak_gain_loss = (body_mask * torch.relu(target_level + weak_gain - output_level)).mean()
    charbonnier = torch.sqrt((enhanced - target).square() + 1e-3 ** 2).mean()
    tv = (
        (enhanced[:, :, :, 1:] - enhanced[:, :, :, :-1]).abs().mean()
        + (enhanced[:, :, 1:, :] - enhanced[:, :, :-1, :]).abs().mean()
    )
    zero = enhanced.new_zeros(())
    heatmap = nn.functional.mse_loss(heatmap_pred, heatmap_target) if heatmap_pred is not None and heatmap_target is not None else zero
    paf = nn.functional.mse_loss(paf_pred, paf_target) if paf_pred is not None and paf_target is not None else zero
    total = (
        heatmap_weight * heatmap + paf_weight * paf + pixel_weight * pixel
        + charbonnier_weight * charbonnier + tv_weight * tv
        + weak_gain_weight * weak_gain_loss
    )
    return total, {
        "heatmap": heatmap.detach(), "paf": paf.detach(), "pixel": pixel.detach(),
        "charbonnier": charbonnier.detach(), "tv": tv.detach(), "weak_gain": weak_gain_loss.detach(),
    }


def train_polishnet(
    model: PolishNetU,
    loader: DataLoader,
    epochs: int = 40,
    lr: float = 1e-3,
    device: str | None = None,
    checkpoint_path: str | Path = "checkpoints/polishnetu_final.pt",
    pixel_weight_end: float | None = None,
    pose_weight: float = 0.0,
    charbonnier_weight: float = 0.1,
    tv_weight: float = 0.05,
    weak_region_weight: float = 2.0,
    weak_gain_weight: float = 0.1,
    weak_gain: float = 0.12,
) -> PolishNetU:
    """Train PolishNetU with real pose targets when the HDF5 file supplies them."""
    if not len(loader.dataset):
        raise ValueError("Cannot train from an empty dataset")
    train_device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    print(f"Using device: {train_device}; pose supervision: {loader.dataset.pose_label_mode}")
    model.to(train_device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.5)
    checkpoint = Path(checkpoint_path)
    paired_denoising = loader.dataset.input_key != loader.dataset.target_key
    pixel_weight_end = pixel_weight_end if pixel_weight_end is not None else (0.5 if paired_denoising else 0.01)
    if not 0.0 < pixel_weight_end <= 1.0:
        raise ValueError("pixel_weight_end must be in (0, 1]")
    if pose_weight < 0.0:
        raise ValueError("pose_weight must be non-negative")
    global_step = 0
    print(
        "Training loop is starting: "
        f"paired_denoising={paired_denoising}, pixel_weight_end={pixel_weight_end:.3f}, "
        f"pose_weight={pose_weight:.3f}, charbonnier_weight={charbonnier_weight:.3f}, tv_weight={tv_weight:.3f}"
    )

    for epoch in range(epochs):
        model.train()
        pixel_weight = 1.0 - (1.0 - pixel_weight_end) * epoch / max(1, epochs - 1)
        total_loss = 0.0
        batches = 0
        for batch, target, label_a, label_b in loader:
            batch = batch.to(train_device, non_blocking=True)
            target = target.to(train_device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            if pose_weight > 0.0 and loader.dataset.pose_label_mode == "joints":
                enhanced, heatmap_pred, paf_pred = model(batch, return_pose=True)
                joints = label_a.to(train_device, non_blocking=True)
                valid = label_b.to(train_device, non_blocking=True)
                heatmap_target, paf_target = build_pose_targets(joints, valid, *batch.shape[-2:])
                loss, _ = composite_loss(
                    enhanced, target, heatmap_pred, heatmap_target, paf_pred, paf_target,
                    pixel_weight, pose_weight, pose_weight, charbonnier_weight, tv_weight,
                    weak_region_weight, weak_gain_weight, weak_gain,
                )
            elif pose_weight > 0.0 and loader.dataset.pose_label_mode == "maps":
                enhanced, heatmap_pred, paf_pred = model(batch, return_pose=True)
                heatmap_target = label_a.to(train_device, non_blocking=True)
                paf_target = label_b.to(train_device, non_blocking=True)
                loss, _ = composite_loss(
                    enhanced, target, heatmap_pred, heatmap_target, paf_pred, paf_target,
                    pixel_weight, pose_weight, pose_weight, charbonnier_weight, tv_weight,
                    weak_region_weight, weak_gain_weight, weak_gain,
                )
            else:
                # Pressure-domain denoising is the default final objective. If
                # joints exist, use them only as a soft body mask; no pose
                # estimator or pose head is trained in this mode.
                enhanced = model(batch)
                heatmap_target = paf_target = None
                if loader.dataset.pose_label_mode == "joints":
                    joints = label_a.to(train_device, non_blocking=True)
                    valid = label_b.to(train_device, non_blocking=True)
                    heatmap_target, paf_target = build_pose_targets(joints, valid, *batch.shape[-2:])
                loss, _ = composite_loss(
                    enhanced, target, heatmap_target=heatmap_target, paf_target=paf_target,
                    pixel_weight=pixel_weight,
                    charbonnier_weight=charbonnier_weight, tv_weight=tv_weight,
                    weak_region_weight=weak_region_weight, weak_gain_weight=weak_gain_weight, weak_gain=weak_gain,
                )
            loss.backward()
            optimizer.step()
            global_step += 1
            total_loss += float(loss.detach())
            batches += 1
        scheduler.step()
        print(
            f"epoch {epoch + 1}/{epochs} loss={total_loss / batches:.5f} "
            f"pixel_weight={pixel_weight:.3f} lr={optimizer.param_groups[0]['lr']:.2e} step={global_step}"
        )

    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "epoch": epochs,
            "pose_label_mode": loader.dataset.pose_label_mode,
            "paf_limbs": PAF_LIMBS,
        },
        checkpoint,
    )
    print(f"Model saved to {checkpoint}")
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train PolishNetU on a pressure HDF5 file")
    parser.add_argument("h5_path")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--base-channels", type=int, default=8)
    parser.add_argument("--checkpoint", default="checkpoints/polishnetu_final.pt")
    parser.add_argument("--pixel-weight-end", type=float, default=None)
    parser.add_argument("--pose-weight", type=float, default=0.0)
    parser.add_argument("--charbonnier-weight", type=float, default=0.1)
    parser.add_argument("--tv-weight", type=float, default=0.05)
    parser.add_argument("--weak-region-weight", type=float, default=2.0)
    parser.add_argument("--weak-gain-weight", type=float, default=0.1)
    parser.add_argument("--weak-gain", type=float, default=0.12)
    args = parser.parse_args()
    dataset = PressureH5Dataset(args.h5_path, max_samples=args.max_samples)
    # HDF5 is opened lazily and Windows uses a single loader process by design.
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, num_workers=0, pin_memory=torch.cuda.is_available())
    train_polishnet(
        PolishNetU(base_channels=args.base_channels), loader, args.epochs,
        lr=args.learning_rate, checkpoint_path=args.checkpoint,
        pixel_weight_end=args.pixel_weight_end, pose_weight=args.pose_weight,
        charbonnier_weight=args.charbonnier_weight, tv_weight=args.tv_weight,
        weak_region_weight=args.weak_region_weight, weak_gain_weight=args.weak_gain_weight,
        weak_gain=args.weak_gain,
    )


if __name__ == "__main__":
    main()
