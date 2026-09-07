"""身体部位划分 UNet 像素级分割模型。

输入 (C, H, W) 压力图(建议插值到 96×48 后送入),
输出 (num_classes, H, W) 的 logits。
"""

from __future__ import annotations

import torch
from torch import nn


class DoubleConv(nn.Module):
    """两次 3×3 卷积 + BN + ReLU。"""

    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class Down(nn.Module):
    """下采样:2×2 maxpool + DoubleConv。"""

    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.MaxPool2d(2),
            DoubleConv(in_channels, out_channels),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class Up(nn.Module):
    """上采样:双线性插值 2× + DoubleConv + skip 连接。"""

    def __init__(self, in_channels: int, skip_channels: int, out_channels: int) -> None:
        super().__init__()
        self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
        self.conv = DoubleConv(in_channels + skip_channels, out_channels)

    def forward(self, x: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        x = self.up(x)
        if x.shape[-2:] != skip.shape[-2:]:
            x = nn.functional.interpolate(
                x, size=skip.shape[-2:], mode="bilinear", align_corners=True
            )
        return self.conv(torch.cat([x, skip], dim=1))


class UNet(nn.Module):
    """轻量 UNet:基通道 32、深度 4,适用于 96×48 压力图。"""

    def __init__(
        self,
        in_channels: int = 1,
        num_classes: int = 6,
        base_channels: int = 32,
    ) -> None:
        super().__init__()
        w = base_channels
        self.inc = DoubleConv(in_channels, w)
        self.down1 = Down(w, w * 2)
        self.down2 = Down(w * 2, w * 4)
        self.down3 = Down(w * 4, w * 8)
        self.down4 = Down(w * 8, w * 16)
        self.up1 = Up(w * 16, w * 8, w * 8)
        self.up2 = Up(w * 8, w * 4, w * 4)
        self.up3 = Up(w * 4, w * 2, w * 2)
        self.up4 = Up(w * 2, w, w)
        self.out = nn.Conv2d(w, num_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)
        x = self.up1(x5, x4)
        x = self.up2(x, x3)
        x = self.up3(x, x2)
        x = self.up4(x, x1)
        return self.out(x)
