"""Visão computacional: classificação de uso do solo em imagens de satélite (EuroSAT).

Objetivo no projeto: medir, em cada setor de Santa Maria, quanto da área é
"construída" (residencial, industrial, vias) e quanto é vegetação. Essa medida
alimenta o índice de vulnerabilidade e a recomendação de plantio de árvores.

Comparamos três abordagens, do mais simples ao mais sofisticado:
  1. Baseline clássico: Random Forest sobre histogramas de cor (sem rede neural);
  2. CNN pequena treinada do zero (3 blocos convolucionais);
  3. ResNet-18 pré-treinada no ImageNet com ajuste fino (transfer learning).

Dados: EuroSAT RGB, 27.000 recortes de 64x64 px do Sentinel-2 em 10 classes.
Divisão estratificada fixa (semente 42): 70% treino, 15% validação, 15% teste.
O modelo final é escolhido pela validação e avaliado UMA vez no teste.

Uso: python -m src.ml.cnn_eurosat
"""
from __future__ import annotations

import io
import json
import time
import zipfile

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from torchvision.models import ResNet18_Weights, resnet18

from src import config as C

SEMENTE = 42
CLASSES = ["AnnualCrop", "Forest", "HerbaceousVegetation", "Highway", "Industrial",
           "Pasture", "PermanentCrop", "Residential", "River", "SeaLake"]
CLASSES_PT = ["Lavoura temporária", "Floresta", "Vegetação herbácea", "Rodovia", "Industrial",
              "Pastagem", "Cultura permanente", "Residencial", "Rio", "Lago/mar"]
# Agrupamento das classes para o uso urbano no projeto
GRUPO = {"AnnualCrop": "vegetacao", "Forest": "vegetacao", "HerbaceousVegetation": "vegetacao",
         "Pasture": "vegetacao", "PermanentCrop": "vegetacao", "Highway": "construido",
         "Industrial": "construido", "Residential": "construido", "River": "agua", "SeaLake": "agua"}

torch.manual_seed(SEMENTE)
np.random.seed(SEMENTE)
torch.set_num_threads(max(1, torch.get_num_threads()))


# --------------------------------------------------------------------------
# Dados
# --------------------------------------------------------------------------
def carregar_eurosat():
    caminho = C.RAW / "eurosat" / "EuroSAT_RGB.zip"
    imgs, rotulos = [], []
    with zipfile.ZipFile(caminho) as z:
        for nome in sorted(z.namelist()):
            if not nome.endswith(".jpg"):
                continue
            classe = nome.split("/")[-2]
            img = Image.open(io.BytesIO(z.read(nome))).convert("RGB")
            imgs.append(np.asarray(img, dtype=np.uint8))
            rotulos.append(CLASSES.index(classe))
    return np.stack(imgs), np.array(rotulos)


def dividir(n, y):
    idx = np.arange(n)
    tr, resto = train_test_split(idx, test_size=0.30, stratify=y, random_state=SEMENTE)
    va, te = train_test_split(resto, test_size=0.50, stratify=y[resto], random_state=SEMENTE)
    return tr, va, te


# --------------------------------------------------------------------------
# 1) Baseline: Random Forest em histogramas de cor
# --------------------------------------------------------------------------
def atributos_cor(X: np.ndarray) -> np.ndarray:
    feats = []
    for c in range(3):
        canal = X[..., c].reshape(len(X), -1)
        hist = np.stack([np.histogram(r, bins=16, range=(0, 256))[0] for r in canal]) / canal.shape[1]
        feats += [hist, canal.mean(1, keepdims=True) / 255, canal.std(1, keepdims=True) / 255]
    return np.hstack(feats)


# --------------------------------------------------------------------------
# 2) CNN pequena do zero  /  3) ResNet-18 com transfer learning
# --------------------------------------------------------------------------
class CNNPequena(nn.Module):
    def __init__(self, n_classes=10):
        super().__init__()

        def bloco(cin, cout):
            return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(),
                                 nn.Conv2d(cout, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(),
                                 nn.MaxPool2d(2))
        self.features = nn.Sequential(bloco(3, 32), bloco(32, 64), bloco(64, 128))
        self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.3), nn.Linear(128, n_classes))

    def forward(self, x):
        return self.head(self.features(x))


def criar_resnet18(n_classes=10, pretreinada=True):
    m = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1 if pretreinada else None)
    m.fc = nn.Linear(m.fc.in_features, n_classes)
    return m


def aumentar(x: torch.Tensor) -> torch.Tensor:
    """Aumento de dados invariante à orientação (imagem de satélite não tem 'lado de cima')."""
    if torch.rand(1) < 0.5:
        x = x.flip(3)
    if torch.rand(1) < 0.5:
        x = x.flip(2)
    return torch.rot90(x, int(torch.randint(0, 4, (1,))), dims=(2, 3))


def para_tensor(X: np.ndarray, media, desvio) -> torch.Tensor:
    t = torch.from_numpy(X).permute(0, 3, 1, 2).float() / 255.0
    return (t - media.view(1, 3, 1, 1)) / desvio.view(1, 3, 1, 1)


def avaliar(modelo, X, y, lote=512):
    modelo.eval()
    preds = []
    with torch.no_grad():
        for i in range(0, len(X), lote):
            preds.append(modelo(X[i:i + lote]).argmax(1))
    p = torch.cat(preds).numpy()
    return p, accuracy_score(y, p)


def treinar(modelo, Xtr, ytr, Xva, yva, epocas, lr, nome, lote=128):
    opt = torch.optim.AdamW(modelo.parameters(), lr=lr, weight_decay=1e-4)
    passos = epocas * int(np.ceil(len(Xtr) / lote))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=passos)
    ytr_t = torch.from_numpy(ytr)
    melhor, estado, historico = 0.0, None, []
    for ep in range(1, epocas + 1):
        modelo.train()
        t0, perm, perda = time.time(), torch.randperm(len(Xtr)), 0.0
        for i in range(0, len(Xtr), lote):
            b = perm[i:i + lote]
            xb, yb = aumentar(Xtr[b]), ytr_t[b]
            opt.zero_grad()
            loss = F.cross_entropy(modelo(xb), yb, label_smoothing=0.05)
            loss.backward()
            opt.step()
            sched.step()
            perda += loss.item() * len(b)
        _, acc = avaliar(modelo, Xva, yva)
        historico.append({"epoca": ep, "perda_treino": perda / len(Xtr), "acuracia_validacao": acc})
        print(f"  [{nome}] época {ep}/{epocas} perda={perda / len(Xtr):.3f} acc_val={acc:.4f} ({time.time() - t0:.0f}s)")
        if acc > melhor:
            melhor, estado = acc, {k: v.detach().clone() for k, v in modelo.state_dict().items()}
    modelo.load_state_dict(estado)
    return modelo, historico


def main():
    t0 = time.time()
    X, y = carregar_eurosat()
    tr, va, te = dividir(len(X), y)
    print(f"EuroSAT: {len(X)} imagens | treino {len(tr)} | validação {len(va)} | teste {len(te)} "
          f"({time.time() - t0:.0f}s para carregar)")
    resultados = {}

    # 1) Baseline
    t1 = time.time()
    F_tr, F_te, F_va = atributos_cor(X[tr]), atributos_cor(X[te]), atributos_cor(X[va])
    rf = RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=SEMENTE).fit(F_tr, y[tr])
    p = rf.predict(F_te)
    resultados["baseline_rf_histograma"] = {"acuracia_teste": accuracy_score(y[te], p),
                                            "f1_macro_teste": f1_score(y[te], p, average="macro"),
                                            "acuracia_validacao": accuracy_score(y[va], rf.predict(F_va)),
                                            "tempo_s": time.time() - t1}
    print(f"Baseline RF: acc_teste={resultados['baseline_rf_histograma']['acuracia_teste']:.4f}")

    # Normalização calculada SOMENTE no treino (evita vazamento de informação)
    t_tr = torch.from_numpy(X[tr]).float() / 255
    media, desvio = t_tr.mean((0, 1, 2)), t_tr.std((0, 1, 2))
    Xtr, Xva, Xte = (para_tensor(X[i], media, desvio) for i in (tr, va, te))

    # 2) CNN pequena
    t1 = time.time()
    cnn, hist_cnn = treinar(CNNPequena(), Xtr, y[tr], Xva, y[va], epocas=8, lr=3e-3, nome="CNN pequena")
    p_cnn, acc = avaliar(cnn, Xte, y[te])
    resultados["cnn_pequena"] = {"acuracia_teste": acc, "f1_macro_teste": f1_score(y[te], p_cnn, average="macro"),
                                 "acuracia_validacao": max(h["acuracia_validacao"] for h in hist_cnn),
                                 "parametros": sum(p.numel() for p in cnn.parameters()),
                                 "tempo_s": time.time() - t1, "historico": hist_cnn}

    # 3) ResNet-18 com transfer learning
    t1 = time.time()
    rn, hist_rn = treinar(criar_resnet18(), Xtr, y[tr], Xva, y[va], epocas=4, lr=1e-3, nome="ResNet-18")
    p_rn, acc = avaliar(rn, Xte, y[te])
    resultados["resnet18_transfer"] = {"acuracia_teste": acc, "f1_macro_teste": f1_score(y[te], p_rn, average="macro"),
                                       "acuracia_validacao": max(h["acuracia_validacao"] for h in hist_rn),
                                       "parametros": sum(p.numel() for p in rn.parameters()),
                                       "tempo_s": time.time() - t1, "historico": hist_rn}

    # Escolha pelo desempenho na VALIDAÇÃO
    nome_final = max(("cnn_pequena", "resnet18_transfer"), key=lambda k: resultados[k]["acuracia_validacao"])
    modelo, p_final = (cnn, p_cnn) if nome_final == "cnn_pequena" else (rn, p_rn)
    resultados["modelo_escolhido"] = nome_final
    resultados["relatorio_por_classe"] = classification_report(y[te], p_final, target_names=CLASSES_PT,
                                                               output_dict=True)
    resultados["matriz_confusao"] = confusion_matrix(y[te], p_final).tolist()
    resultados["classes"] = CLASSES
    resultados["classes_pt"] = CLASSES_PT

    # Acurácia na tarefa que importa para o projeto: construído x vegetação x água
    g = np.array([GRUPO[c] for c in CLASSES])
    resultados["acuracia_grupos_construido_vegetacao_agua"] = float((g[y[te]] == g[p_final]).mean())

    modelo.half()
    torch.save({"arquitetura": nome_final, "estado": modelo.state_dict(), "media": media, "desvio": desvio,
                "classes": CLASSES, "grupo": GRUPO}, C.MODELOS / "cnn_uso_solo.pt")
    (C.MODELOS / "metricas_cnn.json").write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResumo (conjunto de teste, {len(te)} imagens nunca vistas):")
    for k in ("baseline_rf_histograma", "cnn_pequena", "resnet18_transfer"):
        r = resultados[k]
        print(f"  {k:24s} acurácia={r['acuracia_teste']:.4f}  F1-macro={r['f1_macro_teste']:.4f}  tempo={r['tempo_s']:.0f}s")
    print(f"Modelo escolhido: {nome_final} | acurácia construído/vegetação/água: "
          f"{resultados['acuracia_grupos_construido_vegetacao_agua']:.4f}")
    print(f"Total: {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
