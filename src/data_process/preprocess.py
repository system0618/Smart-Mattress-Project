"""Preprocess pressure sequences into Viridis RGB HDF5 datasets."""
from __future__ import annotations
import argparse, json, os
from collections import defaultdict
from pathlib import Path
from typing import Any
import h5py
import matplotlib
import numpy as np
from scipy.io import loadmat
from scipy.ndimage import median_filter

SUPPORTED_EXTENSIONS = {".npy", ".npz", ".csv", ".txt", ".dat", ".mat"}

def _read_file(path: str) -> list[np.ndarray]:
    suffix = Path(path).suffix.lower()
    if suffix == ".npy": return [np.asarray(np.load(path, allow_pickle=False))]
    if suffix == ".npz":
        with np.load(path, allow_pickle=False) as z: return [np.asarray(z[k]) for k in z.files]
    if suffix in {".csv", ".txt", ".dat"}: return [np.loadtxt(path, delimiter=",", ndmin=2)]
    if suffix == ".mat":
        arrays = [v for k, v in loadmat(path).items() if not k.startswith("__") and isinstance(v, np.ndarray) and np.issubdtype(v.dtype, np.number)]
        return [max(arrays, key=lambda x: x.size)] if arrays else []
    return []

def _to_samples(array: np.ndarray) -> list[np.ndarray]:
    """沿时间轴拆帧，并丢弃每个序列开头的 3 帧。"""
    values = np.asarray(array, dtype=np.float32)
    if values.ndim == 2: frames = [values[i:i + 1, :] for i in range(values.shape[0])]
    elif values.ndim >= 3: frames = [np.squeeze(frame) for frame in values]
    else: raise ValueError(f"数组必须至少二维，形状为 {values.shape}")
    if any(frame.ndim != 2 for frame in frames): raise ValueError("单帧必须是二维矩阵")
    return frames[3:]

def _normalize_to_rgb(frames: np.ndarray) -> np.ndarray:
    safe = np.nan_to_num(frames, nan=0.0, posinf=0.0, neginf=0.0)
    low = safe.min(axis=(1, 2), keepdims=True); high = safe.max(axis=(1, 2), keepdims=True)
    return matplotlib.colormaps["viridis"]((safe-low)/np.maximum(high-low, 1e-8))[..., :3].astype(np.float32)

def preprocess_pressure_data(input_dir="data/raw", output_dir="data/processed", train_ratio=0.7, seed=42) -> dict[str, Any]:
    """按父目录用户切分，并将结果流式写入 HDF5。"""
    files = [os.path.join(r,n) for r,_,names in os.walk(input_dir) for n in names if Path(n).suffix.lower() in SUPPORTED_EXTENSIONS]
    by_user: dict[str,list[tuple[str,np.ndarray]]] = defaultdict(list); skipped=[]
    for path in sorted(files):
        user = Path(path).parent.name
        try:
            for array in _read_file(path): by_user[user].extend((path,frame) for frame in _to_samples(array))
        except (OSError,ValueError,TypeError) as exc: skipped.append(f"{path}: {exc}")
    if not by_user: raise ValueError("没有可读取的压力样本")
    shape_counts=defaultdict(int)
    for entries in by_user.values():
        for _,frame in entries: shape_counts[frame.shape]+=1
    expected_shape=max(shape_counts,key=shape_counts.get)+(3,)
    users=list(by_user); np.random.default_rng(seed).shuffle(users)
    cut=max(1,min(len(users)-1,round(len(users)*train_ratio))) if len(users)>1 else 1
    train_users,test_users=users[:cut],users[cut:]
    os.makedirs(output_dir,exist_ok=True); skipped_shapes=[]

    def build(selected:list[str],augment:bool,name:str):
        count=0
        with h5py.File(os.path.join(output_dir,name),"w") as h5:
            data=h5.create_dataset("images",shape=(0,)+expected_shape,maxshape=(None,)+expected_shape,dtype="float32",chunks=True,compression="gzip")
            for user in selected:
                groups=defaultdict(list)
                for source,frame in by_user[user]: groups[frame.shape].append((source,frame))
                for entries in groups.values():
                    raw=np.stack([frame for _,frame in entries])
                    rgb=_normalize_to_rgb(median_filter(raw,size=(3,3,3),mode="nearest"))
                    batch=[]
                    for index,(source,_) in enumerate(entries):
                        if rgb[index].shape!=expected_shape:
                            skipped_shapes.append({"source":os.path.relpath(source,input_dir),"shape":list(rgb[index].shape)}); continue
                        batch.append(rgb[index])
                        if augment: batch.append(rgb[index,:,::-1,:])
                    if batch:
                        values=np.stack(batch); old=data.shape[0]; data.resize(old+values.shape[0],axis=0); data[old:]=values; count+=values.shape[0]
            return tuple(data.shape),count

    train_shape,train_count=build(train_users,True,"train_data.h5")
    test_shape,test_count=build(test_users,False,"test_data.h5")
    manifest={"train_users":train_users,"test_users":test_users,"train_shape":list(train_shape),"test_shape":list(test_shape),"train_count":train_count,"test_count":test_count,"skipped_files":skipped,"expected_shape":list(expected_shape),"skipped_shapes":skipped_shapes}
    with open(os.path.join(output_dir,"manifest.json"),"w",encoding="utf-8") as stream: json.dump(manifest,stream,ensure_ascii=False,indent=2)
    print(f"训练集: {train_shape}；测试集: {test_shape}"); return manifest

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--input-dir",default="data/raw"); parser.add_argument("--output-dir",default="data/processed"); parser.add_argument("--train-ratio",type=float,default=.7); parser.add_argument("--seed",type=int,default=42); args=parser.parse_args(); preprocess_pressure_data(args.input_dir,args.output_dir,args.train_ratio,args.seed)
