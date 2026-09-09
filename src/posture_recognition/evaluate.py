"""Evaluate posture models with accuracy, precision, recall and F1."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import joblib, numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from .dataset import POSTURE_NAMES, load_json_dataset, user_split
from .features import extract_features
from .train import normalize

def evaluate(json_path, model_path, algorithm, train_ratio=.7, skip_frames=3, seed=42, device="auto"):
    data=load_json_dataset(json_path,skip_frames); _,test_i,_,_=user_split(data,train_ratio,seed); images,labels=data.images[test_i],data.labels[test_i]
    if algorithm in {"svm","random_forest"}: predicted=joblib.load(model_path)["model"].predict(extract_features(images))
    elif algorithm == "cnn":
        try:
            import torch
            from .models import TinyPostureCNN
        except ImportError as exc:
            raise RuntimeError("CNN evaluation requires PyTorch; install requirements.txt first") from exc
        device=("cuda" if torch.cuda.is_available() else "cpu") if device=="auto" else device; checkpoint=torch.load(model_path,map_location=device); num_classes=int(checkpoint.get("num_classes", int(labels.max())+1)); model=TinyPostureCNN(num_classes).to(device); model.load_state_dict(checkpoint["model_state"]); model.eval()
        with torch.no_grad(): predicted=model(torch.from_numpy(normalize(images)).unsqueeze(1).to(device)).argmax(1).cpu().numpy()
    else: raise ValueError(f"Unknown algorithm: {algorithm}")
    num_classes=max(int(labels.max()), int(np.max(predicted)))+1; names=POSTURE_NAMES[:num_classes]; class_ids=np.arange(num_classes); report=classification_report(labels,predicted,labels=class_ids,target_names=names,output_dict=True,zero_division=0)
    result={"algorithm":algorithm,"num_classes":num_classes,"class_names":list(names),"accuracy":float(accuracy_score(labels,predicted)),"precision_macro":float(report["macro avg"]["precision"]),"recall_macro":float(report["macro avg"]["recall"]),"f1_macro":float(report["macro avg"]["f1-score"]),"classification_report":report,"confusion_matrix":confusion_matrix(labels,predicted,labels=class_ids).tolist(),"test_samples":int(len(labels))}; print(json.dumps(result,ensure_ascii=False,indent=2)); return result

def main():
    p=argparse.ArgumentParser(); p.add_argument("--json",dest="json_path",type=Path,required=True); p.add_argument("--model-path",type=Path,required=True); p.add_argument("--algorithm",choices=("svm","random_forest","cnn"),required=True); p.add_argument("--train-ratio",type=float,default=.7); p.add_argument("--skip-frames",type=int,default=3); p.add_argument("--seed",type=int,default=42); p.add_argument("--device",default="auto"); evaluate(**vars(p.parse_args()))

if __name__ == "__main__": main()
