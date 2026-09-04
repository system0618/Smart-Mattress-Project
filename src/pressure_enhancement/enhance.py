"""PolishNetU enhancement network and HDF5 training skeleton."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
from typing import Optional
import h5py
import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader
import numpy as np

print("正在初始化框架...")

class PressureH5Dataset(Dataset):
    """懒加载 HDF5 图像，避免把整个数据集读入内存。"""
    def __init__(self, path: str, target_path: Optional[str] = None, max_samples: Optional[int] = None):
        self.path = str(path); self.target_path = str(target_path) if target_path else None
        self._file = None
        print(f"正在读取 HDF5 结构: {self.path}")
        with h5py.File(self.path, "r") as f:
            self.length = min(len(f["images"]), max_samples) if max_samples else len(f["images"])
            self.has_pose_labels = "heatmap" in f and "paf" in f
    def __len__(self): return self.length
    def __getitem__(self, index: int):
        if self._file is None: self._file = h5py.File(self.path, "r")
        image = np.asarray(self._file["images"][index])
        image = np.squeeze(image)
        if image.ndim == 2:
            # 兼容旧版 HDF5 中的 (1, H, W) 或 (H, W) 单通道帧：
            # 复制到 RGB 三个通道，避免卷积层收到 1 通道输入。
            image = np.repeat(image[..., None], 3, axis=-1)
        if image.ndim != 3: raise ValueError(f"单帧应为(H,W,C)，实际为 {image.shape}")
        if image.shape[-1] == 1: image = np.repeat(image, 3, axis=-1)
        if image.shape[-1] != 3: raise ValueError(f"期望 RGB 三通道，实际为 {image.shape}")
        tensor = torch.from_numpy(image.astype(np.float32)).permute(2, 0, 1)
        tensor = tensor * 2.0 - 1.0  # 与网络 tanh 输出对齐
        height, width = tensor.shape[-2:]
        # 暂无真实姿态标注时提供占位目标：OpenPose 风格 14 个关节热图、
        # 28 个 PAF 通道。后续可在这里替换为标注文件读取。
        if self.has_pose_labels:
            heatmap_target = torch.from_numpy(
                np.asarray(self._file["heatmap"][index], dtype=np.float32)
            )
            paf_target = torch.from_numpy(
                np.asarray(self._file["paf"][index], dtype=np.float32)
            )
            if heatmap_target.shape[-2:] != (height, width) or paf_target.shape[-2:] != (height, width):
                raise ValueError(
                    "Pose label size does not match the pressure image. "
                    "Regenerate heatmap/paf labels before training."
                )
        else:
            heatmap_target = torch.zeros((14, height, width), dtype=torch.float32)
            paf_target = torch.zeros((28, height, width), dtype=torch.float32)
        return tensor, heatmap_target, paf_target
    def __del__(self):
        if self._file is not None: self._file.close()

class _Down(nn.Module):
    def __init__(self, cin, cout):
        # 3x3 卷积在宽度已经降到 1 时仍可工作；4x4 卷积会因有效输入过小报错。
        super().__init__(); self.block = nn.Sequential(nn.Conv2d(cin, cout, 3, 2, 1), nn.BatchNorm2d(cout), nn.LeakyReLU(.2, inplace=True))
    def forward(self, x): return self.block(x)

class _Up(nn.Module):
    def __init__(self, cin, cout):
        super().__init__(); self.block = nn.Sequential(nn.Upsample(scale_factor=2, mode="nearest"), nn.Conv2d(cin, cout, 3, 1, 1), nn.BatchNorm2d(cout), nn.LeakyReLU(.2, inplace=True))
    def forward(self, x): return self.block(x)

class PolishNetU(nn.Module):
    """8 层 U-Net 风格域适配网络，输出增强后的 RGB 特征图。"""
    def __init__(self, in_channels=3, out_channels=3, base_channels=8):
        super().__init__()
        widths = [min(base_channels * 2 ** i, 512) for i in range(8)]
        self.encoder = nn.ModuleList([_Down(in_channels if i == 0 else widths[i-1], widths[i]) for i in range(8)])
        decoder_in = [widths[7]] + [widths[7-i] + widths[8-i] for i in range(1, 8)]
        decoder_out = [widths[6-i] for i in range(7)] + [base_channels]
        self.decoder = nn.ModuleList([_Up(cin, cout) for cin, cout in zip(decoder_in, decoder_out)])
        self.output = nn.Sequential(nn.Conv2d(base_channels + widths[0] + in_channels, out_channels, 3, 1, 1), nn.Tanh())
    def forward(self, x):
        skips = []; h = x
        for layer in self.encoder: h = layer(h); skips.append(h)
        for i, layer in enumerate(self.decoder):
            skip = skips[-1-i]
            h = layer(h)
            h = torch.nn.functional.interpolate(h, size=skip.shape[-2:], mode="nearest")
            h = torch.cat([h, skip], dim=1)
        h = torch.nn.functional.interpolate(h, size=x.shape[-2:], mode="nearest")
        return self.output(torch.cat([h, x], dim=1))

def composite_loss(enhanced, target, heatmap_pred=None, heatmap_target=None, paf_pred=None, paf_target=None, pixel_weight=1.0):
    """计算 E_heatmap + E_PAF + pixel_weight * E_pixel。"""
    mse = nn.functional.mse_loss
    pixel = mse(enhanced, target)
    heatmap = mse(heatmap_pred, heatmap_target) if heatmap_pred is not None and heatmap_target is not None else enhanced.new_zeros(())
    paf = mse(paf_pred, paf_target) if paf_pred is not None and paf_target is not None else enhanced.new_zeros(())
    return heatmap + paf + pixel_weight * pixel, {"heatmap": heatmap.detach(), "paf": paf.detach(), "pixel": pixel.detach()}

def train_polishnet(model, loader, epochs=40, lr=1e-3, device=None):
    """训练骨架：每 1000 次更新学习率乘 0.95，像素权重从 1 衰减到 0.01。"""
    device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu")); print(f"使用设备: {device}"); model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    # 每 10 个 epoch 衰减为原学习率的 0.5，避免按 batch 衰减导致学习率快速归零。
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.5)
    print("训练循环即将开始...")
    step = 0
    for epoch in range(epochs):
        model.train(); pixel_weight = max(.01, 1.0 - .99 * epoch / max(1, epochs - 1))
        for batch, heatmap_target, paf_target in loader:
            batch = batch.to(device); heatmap_target = heatmap_target.to(device); paf_target = paf_target.to(device)
            optimizer.zero_grad(); output = model(batch)
            # 占位姿态预测：由网络输出构造可反向传播的预测张量。
            base = output.mean(dim=1, keepdim=True)
            heatmap_pred = base.expand(-1, 14, -1, -1)
            paf_pred = base.expand(-1, 28, -1, -1)
            loss, parts = composite_loss(output, batch, heatmap_pred, heatmap_target, paf_pred, paf_target, pixel_weight)
            loss.backward(); optimizer.step(); step += 1
        scheduler.step()
        print(f"epoch {epoch+1}/{epochs} loss={loss.item():.5f} pixel_weight={pixel_weight:.3f} lr={optimizer.param_groups[0]['lr']:.2e} step={step}")
    os.makedirs("checkpoints", exist_ok=True)
    torch.save({"model_state_dict": model.state_dict(), "optimizer_state_dict": optimizer.state_dict(), "epoch": epochs}, "checkpoints/polishnetu_final.pt")
    print("模型已保存到 checkpoints/polishnetu_final.pt")
    return model

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("h5_path"); p.add_argument("--epochs",type=int,default=40); p.add_argument("--batch-size",type=int,default=16); p.add_argument("--max-samples",type=int,default=None); p.add_argument("--base-channels",type=int,default=8); a=p.parse_args()
    dataset = PressureH5Dataset(a.h5_path, max_samples=a.max_samples)
    loader = DataLoader(dataset, batch_size=a.batch_size, shuffle=True, num_workers=0)
    train_polishnet(PolishNetU(base_channels=a.base_channels), loader, a.epochs)
