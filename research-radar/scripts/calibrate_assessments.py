"""Compare evidence-based priorities with human labels; no invented benchmark."""
from __future__ import annotations

import math
from pathlib import Path
import json
from assessment import AssessmentError, finite, load_jsonl


def ranks(values):
    ordered = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and values[ordered[j]] == values[ordered[i]]:
            j += 1
        for k in range(i, j):
            result[ordered[k]] = (i + 1 + j) / 2
        i = j
    return result


def spearman(left, right):
    if len(left) < 3:
        return None
    a, b = ranks(left), ranks(right)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    denominator = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / denominator, 4) if denominator else None


def evaluate(records, labels, top_k=10):
    if type(top_k) is not int or top_k < 1:
        raise AssessmentError("top_k must be a positive integer")
    ids = [r.get("id") for r in records]
    gold = {}
    for label in labels:
        key = label.get("candidate_id")
        if key not in ids or key in gold:
            raise AssessmentError("Gold labels must have unique candidate IDs present in the ranking")
        if any(label.get(axis) is not None and not finite(label[axis], 0, 100) for axis in ("quality", "match")):
            raise AssessmentError("Human quality/match labels must be numbers in [0,100]")
        if label.get("selected") is not None and type(label["selected"]) is not bool:
            raise AssessmentError("Human selected label must be a Boolean")
        gold[key] = label
    axes = {}
    for axis in ("quality", "match"):
        pairs = [(r["assessment"][axis]["score"], gold[r["id"]][axis]) for r in records if r["id"] in gold
                 and gold[r["id"]].get(axis) is not None and r["assessment"][axis]["score"] is not None]
        axes[axis] = {"paired_n": len(pairs), "mae": round(sum(abs(a - b) for a, b in pairs) / len(pairs), 3) if pairs else None,
                      "signed_bias": round(sum(a - b for a, b in pairs) / len(pairs), 3) if pairs else None,
                      "spearman": spearman([p[0] for p in pairs], [p[1] for p in pairs])}
    recommended = sorted([r for r in records if r["assessment"]["status"] in {"must_read", "shortlist"}],
                         key=lambda r: r["assessment"]["composite"]["score"], reverse=True)[:top_k]
    annotated = [r for r in recommended if type(gold.get(r["id"], {}).get("selected")) is bool]
    # An unlabelled recommendation must not silently count as success/failure.
    precision = sum(gold[r["id"]]["selected"] for r in annotated) / len(annotated) if annotated and len(annotated) == len(recommended) else None
    false_positives = [r["id"] for r in annotated if gold[r["id"]]["selected"] is False]
    discrepancies = [{"candidate_id": r["id"], "axis": axis, "llm": r["assessment"][axis]["score"], "human": gold[r["id"]][axis]}
                     for r in records if r["id"] in gold for axis in ("quality", "match")
                     if gold[r["id"]].get(axis) is not None and r["assessment"][axis]["score"] is not None
                     and abs(r["assessment"][axis]["score"] - gold[r["id"]][axis]) >= 20]
    return {"human_labels": len(labels), "quality": axes["quality"], "match": axes["match"],
            "top_k": top_k, "recommended_n": len(recommended), "annotated_recommendations": len(annotated),
            "precision_at_k": round(precision, 4) if precision is not None else None,
            "false_positive_ids": false_positives, "large_disagreements": discrepancies,
            "scope": "Agreement with supplied human labels only; no accuracy claim for unseen fields or unlabelled papers",
            "calibration_note": "Use a held-out set and repeated host reviews; do not tune and report performance on the same examples"}


def run(ranked_path, gold_path, output, top_k=10):
    output = Path(output)
    if output.exists():
        raise AssessmentError("Calibration output already exists")
    result = evaluate(load_jsonl(ranked_path), load_jsonl(gold_path), top_k)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result
