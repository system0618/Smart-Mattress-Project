"""Train PolishNetU for annotated pressure-map enhancement.

The target remains a denoised pressure map.  Region/spine annotations only
reweight the body pixels, so the network cannot improve the score by changing
the empty mattress background.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import h5py
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

from .enhance import PolishNetU, build_pose_targets
from .visualize_enhancement import save_comparison


class AnnotatedPressureDataset(Dataset):
    def __init__(self, path: str | Path, max_samples: int | None = None) -> None:
        self.path = str(path)
        self._file: h5py.File | None = None
        with h5py.File(self.path, "r") as file:
            for key in ("input_images", "target_images", "body_mask", "joints", "joint_valid"):
                if key not in file:
                    raise KeyError(f"{self.path} lacks '{key}'")
            available = len(file["input_images"])
            self.length = min(available, max_samples) if max_samples is not None else available

    def __len__(self) -> int:
        return self.length

    def _open(self) -> h5py.File:
        if self._file is None:
            self._file = h5py.File(self.path, "r")
        return self._file

    def __getitem__(self, index: int):
        file = self._open()
        image = torch.from_numpy(np.asarray(file["input_images"][index], dtype=np.float32)).permute(2, 0, 1)
        target = torch.from_numpy(np.asarray(file["target_images"][index], dtype=np.float32)).permute(2, 0, 1)
        mask = torch.from_numpy(np.asarray(file["body_mask"][index], dtype=np.float32))[None]
        joints = torch.from_numpy(np.asarray(file["joints"][index], dtype=np.float32))
        joint_valid = torch.from_numpy(np.asarray(file["joint_valid"][index], dtype=np.float32))
        return image * 2.0 - 1.0, target * 2.0 - 1.0, mask, joints, joint_valid

    def __del__(self) -> None:
        if self._file is not None:
            self._file.close()


def enhancement_loss(
    output: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
    region_weight: float = 3.0,
    gain_weight: float = 0.15,
    gain: float = 0.08,
    tv_weight: float = 0.05,
    heatmap_pred: torch.Tensor | None = None,
    heatmap_target: torch.Tensor | None = None,
    paf_pred: torch.Tensor | None = None,
    paf_target: torch.Tensor | None = None,
    heatmap_weight: float = 0.05,
    paf_weight: float = 0.05,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Weighted pressure reconstruction with weak-body gain and TV terms."""
    mask = mask.clamp(0.0, 1.0)
    error = (output - target).square().mean(dim=1, keepdim=True)
    pixel = ((1.0 + region_weight * mask) * error).mean()
    output_level = (output + 1.0).mean(dim=1, keepdim=True) * 0.5
    target_level = (target + 1.0).mean(dim=1, keepdim=True) * 0.5
    gain_loss = (mask * torch.relu(target_level + gain - output_level)).mean()
    tv = (
        (output[:, :, :, 1:] - output[:, :, :, :-1]).abs().mean()
        + (output[:, :, 1:, :] - output[:, :, :-1, :]).abs().mean()
    )
    charbonnier = torch.sqrt((output - target).square() + 1e-6).mean()
    heatmap_loss = output.new_zeros(())
    paf_loss = output.new_zeros(())
    if heatmap_pred is not None and heatmap_target is not None:
        heatmap_loss = nn.functional.mse_loss(heatmap_pred, heatmap_target)
    if paf_pred is not None and paf_target is not None:
        paf_loss = nn.functional.mse_loss(paf_pred, paf_target)
    total = (
        pixel
        + gain_weight * gain_loss
        + tv_weight * tv
        + 0.1 * charbonnier
        + heatmap_weight * heatmap_loss
        + paf_weight * paf_loss
    )
    return total, {
        "pixel": float(pixel.detach()),
        "gain": float(gain_loss.detach()),
        "tv": float(tv.detach()),
        "heatmap": float(heatmap_loss.detach()),
        "paf": float(paf_loss.detach()),
    }


def train(
    train_h5: str | Path,
    test_h5: str | Path,
    checkpoint: str | Path,
    epochs: int = 20,
    batch_size: int = 32,
    base_channels: int = 8,
    learning_rate: float = 1e-3,
    heatmap_weight: float = 0.05,
    paf_weight: float = 0.05,
    max_samples: int | None = None,
    residual_scale: float = 0.6,
) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_set = AnnotatedPressureDataset(train_h5, max_samples=max_samples)
    test_set = AnnotatedPressureDataset(test_h5, max_samples=max_samples)
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, num_workers=0, pin_memory=device.type == "cuda")
    test_loader = DataLoader(test_set, batch_size=batch_size, shuffle=False, num_workers=0, pin_memory=device.type == "cuda")
    model = PolishNetU(base_channels=base_channels, residual_scale=residual_scale).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.5)
    # RTX 30 系列支持 Tensor Core；混合精度可降低显存和卷积耗时。
    amp_enabled = device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp_enabled)
    print(f"Annotated pressure training on {device}: {len(train_set)} train / {len(test_set)} test")
    for epoch in range(epochs):
        model.train()
        running = 0.0
        for image, target, mask, joints, valid in tqdm(train_loader, desc=f"epoch {epoch + 1}/{epochs}", unit="batch"):
            image, target, mask = image.to(device, non_blocking=True), target.to(device, non_blocking=True), mask.to(device, non_blocking=True)
            joints, valid = joints.to(device, non_blocking=True), valid.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=amp_enabled):
                output, heatmap_pred, paf_pred = model(image, return_pose=True)
                heatmap_target, paf_target = build_pose_targets(joints, valid, image.shape[-2], image.shape[-1])
                loss, _ = enhancement_loss(
                    output, target, mask,
                    heatmap_pred=heatmap_pred, heatmap_target=heatmap_target,
                    paf_pred=paf_pred, paf_target=paf_target,
                    heatmap_weight=heatmap_weight, paf_weight=paf_weight,
                )
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            running += float(loss.detach())
        scheduler.step()
        model.eval()
        test_loss = 0.0
        with torch.inference_mode():
            for image, target, mask, joints, valid in test_loader:
                image, target, mask = image.to(device), target.to(device), mask.to(device)
                joints, valid = joints.to(device), valid.to(device)
                output, heatmap_pred, paf_pred = model(image, return_pose=True)
                heatmap_target, paf_target = build_pose_targets(joints, valid, image.shape[-2], image.shape[-1])
                test_loss += float(enhancement_loss(
                    output, target, mask,
                    heatmap_pred=heatmap_pred, heatmap_target=heatmap_target,
                    paf_pred=paf_pred, paf_target=paf_target,
                    heatmap_weight=heatmap_weight, paf_weight=paf_weight,
                )[0])
        print(f"epoch {epoch + 1}/{epochs} train_loss={running / len(train_loader):.5f} test_loss={test_loss / len(test_loader):.5f} lr={scheduler.get_last_lr()[0]:.2e}")
    destination = Path(checkpoint)
    destination.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "epoch": epochs,
        "base_channels": base_channels,
        "residual_scale": residual_scale,
    }, destination)
    print(f"Model saved to {destination}")


def export(
    model_checkpoint: str | Path,
    input_h5: str | Path,
    output_h5: str | Path,
    batch_size: int = 32,
    comparison_output: str | Path = "../压力增强对比图/关节标注模型/annotated_test_comparison.png",
) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(model_checkpoint, map_location="cpu", weights_only=False)
    model = PolishNetU(
        base_channels=int(state.get("base_channels", 8)),
        residual_scale=float(state.get("residual_scale", 0.125)),
    ).to(device)
    model.load_state_dict(state["model_state_dict"])
    model.eval()
    dataset = AnnotatedPressureDataset(input_h5)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    with h5py.File(output_h5, "w") as target_file:
        count, _, height, width = len(dataset), 3, 24, 44
        with h5py.File(input_h5, "r") as source:
            _, height, width, channels = source["input_images"].shape
        output = target_file.create_dataset("images", shape=(count, height, width, channels), dtype="uint8", compression="gzip")
        offset = 0
        with torch.inference_mode():
            for image, _, _, _, _ in tqdm(loader, desc="export enhancement", unit="batch"):
                prediction = ((model(image.to(device)) + 1.0) * 127.5).clamp(0, 255).byte().permute(0, 2, 3, 1).cpu().numpy()
                output[offset:offset + len(prediction)] = prediction
                offset += len(prediction)
        target_file.attrs["model"] = "PolishNetU annotated pressure enhancement"
    print(f"Enhanced data saved to {output_h5}")
    # Keep visual QA beside the enhancement module for the project handoff.
    save_comparison(input_h5, output_h5, comparison_output, count=6, selection="largest-difference")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train/export annotated pressure enhancement")
    sub = parser.add_subparsers(dest="command", required=True)
    fit = sub.add_parser("train")
    fit.add_argument("--train-h5", required=True); fit.add_argument("--test-h5", required=True); fit.add_argument("--checkpoint", required=True)
    fit.add_argument("--epochs", type=int, default=20); fit.add_argument("--batch-size", type=int, default=32); fit.add_argument("--base-channels", type=int, default=8)
    fit.add_argument("--heatmap-weight", type=float, default=0.05); fit.add_argument("--paf-weight", type=float, default=0.05)
    fit.add_argument("--max-samples", type=int)
    fit.add_argument("--residual-scale", type=float, default=0.6)
    out = sub.add_parser("export")
    out.add_argument("--input-h5", required=True); out.add_argument("--checkpoint", required=True); out.add_argument("--output-h5", required=True); out.add_argument("--batch-size", type=int, default=32)
    out.add_argument("--comparison-output", default="../压力增强对比图/关节标注模型/annotated_test_comparison.png")
    args = parser.parse_args()
    if args.command == "train":
        train(
            args.train_h5, args.test_h5, args.checkpoint, args.epochs,
            args.batch_size, args.base_channels,
            heatmap_weight=args.heatmap_weight, paf_weight=args.paf_weight,
            max_samples=args.max_samples,
            residual_scale=args.residual_scale,
        )
    else:
        export(args.checkpoint, args.input_h5, args.output_h5, args.batch_size, args.comparison_output)


if __name__ == "__main__":
    main()
