"""Lightweight CNN for pressure-map posture classification."""
from __future__ import annotations
import torch
from torch import nn

class TinyPostureCNN(nn.Module):
    def __init__(self, num_classes: int = 6) -> None:
        super().__init__()
        self.features = nn.Sequential(nn.Conv2d(1,16,3,padding=1), nn.BatchNorm2d(16), nn.ReLU(), nn.MaxPool2d(2), nn.Conv2d(16,32,3,padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2), nn.Conv2d(32,64,3,padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((1,1)))
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(.2), nn.Linear(64, num_classes))
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))
