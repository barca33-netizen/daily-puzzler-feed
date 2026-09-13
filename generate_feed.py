#!/usr/bin/env python3
"""Build five CC0/public-domain colour-by-number puzzles from Openverse."""

from __future__ import annotations

import hashlib
import io
import json
import random
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageFilter, ImageOps
from skimage.segmentation import find_boundaries, slic

API = "https://api.openverse.org/v1/images/"
RAW_ROOT = "https://raw.githubusercontent.com/barca33-netizen/daily-puzzler-feed/main/feed"
OUT = Path("feed")
SIZE = 720
REGIONS = 760
COLOURS = 120
TOPICS = [
    ("Wildlife Portrait", "detailed wildlife animal illustration"),
    ("Woodland Scene", "detailed woodland animals forest illustration"),
    ("Ocean Life", "detailed sea animal underwater illustration"),
    ("Garden Life", "detailed bird butterfly flowers illustration"),
    ("Countryside", "detailed countryside animal landscape illustration"),
    ("Big Cats", "detailed lion tiger leopard illustration"),
    ("Mountain Wildlife", "detailed mountain wildlife landscape illustration"),
    ("Tropical Nature", "detailed tropical birds animals illustration"),
]


def get_json(url: str, **params):
    response = requests.get(url, params=params, timeout=35, headers={"User-Agent": "DailyPuzzler/1.0"})
    response.raise_for_status()
    return response.json()


def download(url: str) -> Image.Image:
    response = requests.get(url, timeout=45, headers={"User-Agent": "DailyPuzzler/1.0"}, stream=True)
    response.raise_for_status()
    content = response.raw.read(14_000_001)
    if len(content) > 14_000_000:
        raise ValueError("image too large")
    image = Image.open(io.BytesIO(content))
    image.load()
    return ImageOps.exif_transpose(image).convert("RGB")


def candidates(query: str, seed: int):
    data = get_json(API, q=query, license="cc0,pdm", page_size=80, mature="false")
    results = [x for x in data.get("results", []) if x.get("url") and x.get("license") in {"cc0", "pdm"}]
    random.Random(seed).shuffle(results)
    return results


def prepare(image: Image.Image) -> np.ndarray:
    width, height = image.size
    if min(width, height) < 450:
        raise ValueError("source resolution too small")
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    image = image.filter(ImageFilter.MedianFilter(3))
    return np.asarray(image, dtype=np.uint8)


def palette_for(means: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sample = Image.fromarray(means.reshape(1, len(means), 3).astype(np.uint8), "RGB")
    quantized = sample.quantize(colors=min(COLOURS, len(means)), method=Image.Quantize.MEDIANCUT)
    raw_palette = np.asarray(quantized.getpalette()[: COLOURS * 3], dtype=np.uint8).reshape(-1, 3)
    used = np.unique(np.asarray(quantized))
    palette = raw_palette[used]
    distances = ((means[:, None, :].astype(np.int32) - palette[None, :, :].astype(np.int32)) ** 2).sum(axis=2)
    return palette, distances.argmin(axis=1)


def convert(source: dict, target: Path, day_seed: int, slot: int, category: str) -> dict:
    image = prepare(download(source["url"]))
    labels = slic(image, n_segments=REGIONS, compactness=14, sigma=1.1, start_label=1, channel_axis=-1)
    ids = np.unique(labels)
    if len(ids) < 420:
        raise ValueError("not enough useful regions")

    means = np.array([image[labels == region_id].mean(axis=0) for region_id in ids])
    palette, assignments = palette_for(means)
    order = list(range(len(palette)))
    random.Random(day_seed + slot * 7919).shuffle(order)
    remap = {old: new for new, old in enumerate(order)}
    shuffled_palette = palette[order]
    assignments = np.array([remap[int(x)] for x in assignments])

    complete = np.zeros_like(image)
    mask = np.zeros_like(image)
    regions = []
    for index, region_id in enumerate(ids):
        pixels = labels == region_id
        complete[pixels] = shuffled_palette[assignments[index]]
        encoded = int(region_id)
        mask[pixels] = ((encoded >> 16) & 255, (encoded >> 8) & 255, encoded & 255)
        yy, xx = np.where(pixels)
        regions.append({
            "id": encoded,
            "colour": int(assignments[index]),
            "x": round(float(xx.mean() / SIZE), 6),
            "y": round(float(yy.mean() / SIZE), 6),
            "area": int(len(xx)),
        })

    edges = find_boundaries(labels, mode="thick")
    blank = np.full_like(image, 255)
    blank[edges] = (35, 42, 61)
    target.mkdir(parents=True, exist_ok=True)
    Image.fromarray(blank).save(target / "blank.png", optimize=True)
    Image.fromarray(complete).save(target / "complete.png", optimize=True)
    Image.fromarray(mask).save(target / "mask.png", optimize=True)

    metadata = {
        "palette": shuffled_palette.astype(int).tolist(),
        "regions": regions,
        "source": {
            "title": source.get("title") or category,
            "creator": source.get("creator") or "Unknown",
            "license": source.get("license", "").upper(),
            "licenseUrl": source.get("license_url") or "",
            "pageUrl": source.get("foreign_landing_url") or source.get("url"),
            "provider": source.get("provider") or source.get("source") or "Openverse",
        },
    }
    (target / "meta.json").write_text(json.dumps(metadata, separators=(",", ":")), encoding="utf-8")
    title = source.get("title") or category
    return {
        "id": hashlib.sha256(f"{date.today()}:{source.get('id', title)}".encode()).hexdigest()[:16],
        "title": title[:70],
        "subtitle": f"{category} • {len(regions)} shaped regions • {len(shuffled_palette)} colours",
        "path": target.name,
        "source": metadata["source"],
    }


def main():
    today = date.today().isoformat()
    seed = int(today.replace("-", ""))
    rng = random.Random(seed)
    topics = rng.sample(TOPICS, 5)
    day_dir = OUT / today
    if day_dir.exists():
        shutil.rmtree(day_dir)
    entries = []
    used = set()
    for slot, (category, query) in enumerate(topics, 1):
        errors = []
        for source in candidates(query, seed + slot):
            source_id = source.get("id") or source.get("url")
            if source_id in used:
                continue
            try:
                item_dir = day_dir / f"picture-{slot}"
                entry = convert(source, item_dir, seed, slot, category)
                entry["baseUrl"] = f"{RAW_ROOT}/{today}/{item_dir.name}"
                entries.append(entry)
                used.add(source_id)
                break
            except Exception as exc:
                errors.append(str(exc))
        else:
            raise RuntimeError(f"Could not build slot {slot}: {errors[-5:]}")

    manifest = {"schema": 1, "date": today, "generatedAt": f"{today}T00:05:00Z", "pictures": entries}
    OUT.mkdir(exist_ok=True)
    (OUT / "current.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (day_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    dated = sorted(p for p in OUT.iterdir() if p.is_dir())
    for old in dated[:-14]:
        shutil.rmtree(old)


if __name__ == "__main__":
    main()
