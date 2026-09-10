"""Train sleep-posture recognition baselines."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from .dataset import POSTURE_NAMES, load_json_dataset, user_split
from .features import extract_features

def normalize(images):
    low = images.min(axis=(1,2), keepdims=True); high = images.max(axis=(1,2), keepdims=True)
    return (images-low) / np.maximum(high-low, 1e-6)

def train_traditional(images, labels, algorithm, seed):
    x = extract_features(images)
    if algorithm == "svm":
        model = Pipeline([("scale", StandardScaler()), ("classifier", SVC(C=10.0, gamma="scale", kernel="rbf", probability=True, random_state=seed))])
    elif algorithm == "random_forest":
        model = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=seed, n_jobs=-1)
    else: raise ValueError(f"Unsupported traditional algorithm: {algorithm}")
    model.fit(x, labels); return model

def train_cnn(images, labels, model_path, num_classes, epochs=30, batch_size=128, lr=1e-3, seed=42, device="auto"):
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
        from .models import TinyPostureCNN
    except ImportError as exc:
        raise RuntimeError("CNN training requires PyTorch; install requirements.txt first") from exc
    torch.manual_seed(seed); np.random.seed(seed)
    device = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
    x, y = torch.from_numpy(normalize(images)).unsqueeze(1), torch.from_numpy(labels)
    loader = DataLoader(TensorDataset(x, y), batch_size=batch_size, shuffle=True)
    model = TinyPostureCNN(num_classes).to(device); optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4); criterion = nn.CrossEntropyLoss(); history=[]
    for epoch in range(1, epochs+1):
        model.train(); loss_sum=0.0; correct=0
        for batch_x, batch_y in loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            noisy = (batch_x * torch.empty_like(batch_x).uniform_(.95,1.05) + torch.randn_like(batch_x)*.01).clamp(0,1)
            optimizer.zero_grad(set_to_none=True); logits=model(noisy); loss=criterion(logits,batch_y); loss.backward(); optimizer.step()
            loss_sum += loss.item()*len(batch_y); correct += (logits.argmax(1)==batch_y).sum().item()
        record={"epoch":epoch,"loss":loss_sum/len(y),"accuracy":correct/len(y)}; history.append(record)
        print(f"[posture][cnn] epoch={epoch:03d} loss={record['loss']:.4f} accuracy={record['accuracy']:.4f}")
    model_path.parent.mkdir(parents=True, exist_ok=True); torch.save({"model_state":model.state_dict(),"classes":list(POSTURE_NAMES),"input_size":[44,24]}, model_path)
    return {"device":device,"history":history}

def train(json_path, model_dir, algorithm, train_ratio=.7, skip_frames=3, seed=42, epochs=30, device="auto"):
    dataset=load_json_dataset(json_path, skip_frames); train_i,test_i,train_users,test_users=user_split(dataset,train_ratio,seed); model_dir.mkdir(parents=True,exist_ok=True)
    if algorithm in {"svm","random_forest"}:
        path=model_dir/f"{algorithm}.joblib"; joblib.dump({"model":train_traditional(dataset.images[train_i],dataset.labels[train_i],algorithm,seed),"classes":list(POSTURE_NAMES)},path); extra={"model_path":str(path)}
    elif algorithm == "cnn":
        path=model_dir/"cnn.pt"; num_classes=int(dataset.labels.max())+1; extra={"model_path":str(path),"num_classes":num_classes,**train_cnn(dataset.images[train_i],dataset.labels[train_i],path,num_classes=num_classes,epochs=epochs,seed=seed,device=device)}
    else: raise ValueError(f"Unknown algorithm: {algorithm}")
    metadata={"algorithm":algorithm,"classes":list(POSTURE_NAMES),"json_path":str(json_path),"train_ratio":train_ratio,"seed":seed,"skip_frames":skip_frames,"train_samples":int(len(train_i)),"test_samples":int(len(test_i)),"train_users":train_users,"test_users":test_users,"test_indices":test_i.tolist(),**extra}
    (model_dir/f"{algorithm}_split.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8"); return metadata

def main():
    p=argparse.ArgumentParser(); p.add_argument("--json",dest="json_path",type=Path,required=True); p.add_argument("--model-dir",type=Path,default=Path("src/posture_recognition/models")); p.add_argument("--algorithm",choices=("svm","random_forest","cnn"),default="svm"); p.add_argument("--train-ratio",type=float,default=.7); p.add_argument("--skip-frames",type=int,default=3); p.add_argument("--epochs",type=int,default=30); p.add_argument("--seed",type=int,default=42); p.add_argument("--device",default="auto"); train(**vars(p.parse_args()))

if __name__ == "__main__": main()
