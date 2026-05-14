from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
THEME_ROOT = REPO_ROOT / "DN-experiment-2.0"
DOC_RUNS_ROOT = REPO_ROOT / "external" / "doc-storygen-v2" / "scripts" / "dn_runs"
BASELINE_IMAGE_ROOT = REPO_ROOT / "experiments" / "baselines" / "same_model_fair_compare" / "generated"
SITE_DATA_ROOT = REPO_ROOT / "human_eval_site" / "data"
SITE_ASSETS_ROOT = REPO_ROOT / "human_eval_site" / "assets" / "themes"

IMAGE_SYSTEMS = ["dn", "ic_lora", "sdm_v2", "storydiffusion"]

TEXT_DIMENSIONS = [
    {"id": "text_consistency", "label": "文本一致性", "help": "是否符合题目、剧情设定、人物关系与前后文逻辑。"},
    {"id": "text_quality", "label": "文本质量", "help": "叙事是否清楚、连贯、具体、可读。"},
    {"id": "overall", "label": "综合评分", "help": "文本方案的整体质量。"},
]

IMAGE_DIMENSIONS = [
    {"id": "image_consistency", "label": "图片一致性", "help": "人物、场景、动作、道具与给定段落是否一致。"},
    {"id": "sequence_consistency", "label": "连续性", "help": "同一方案内多段图片在风格、角色与时间推进上是否连续。"},
    {"id": "visual_quality", "label": "视觉质量", "help": "图片是否清晰自然，是否存在明显崩坏、伪影或异常。"},
    {"id": "image_text_alignment", "label": "图文匹配", "help": "每段图片是否准确表达对应段落的文本内容。"},
    {"id": "overall", "label": "综合评分", "help": "该方案在图像一致性任务下的整体质量。"},
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clip_preview(text: str, max_length: int = 28) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 1] + "…"


def normalize_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def split_sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[。！？!?])\s*", text.strip())
    return [c.strip() for c in chunks if c.strip()]


def load_dn_story_segments(theme_dir: Path, game_id: str, segments: int) -> list[str] | None:
    output: list[str] = []
    for idx in range(1, segments + 1):
        segment_json = theme_dir / f"{game_id}_{idx:03d}.json"
        if not segment_json.exists():
            return None
        scene = str(load_json(segment_json).get("scene") or "").strip()
        if not scene:
            return None
        output.append(scene)
    return output


def find_latest_doc_run(theme_numeric_id: str) -> Path | None:
    pattern = f"doc_theme{theme_numeric_id}_*_doc"
    candidates = [p for p in DOC_RUNS_ROOT.glob(pattern) if p.is_dir()]
    if not candidates:
        return None
    for run_dir in sorted(candidates, key=lambda p: p.name, reverse=True):
        story_txt = run_dir / "story.txt"
        if story_txt.exists() and story_txt.stat().st_size > 0:
            return run_dir
    return None


def load_doc_story_segments(theme_numeric_id: str, segments: int) -> list[str] | None:
    run_dir = find_latest_doc_run(theme_numeric_id)
    if run_dir is None:
        return None
    story_txt = run_dir / "story.txt"
    if not story_txt.exists():
        return None
    raw = story_txt.read_text(encoding="utf-8", errors="replace")
    lines = normalize_lines(raw)
    if len(lines) >= segments:
        return lines[:segments]
    sentences = split_sentences(raw)
    if len(sentences) >= segments:
        return sentences[:segments]
    return None


def resolve_baseline_image(system: str, game_id: str, idx: int) -> Path | None:
    exact = BASELINE_IMAGE_ROOT / system / "images" / f"{game_id}_seg_{idx:03d}.png"
    if exact.exists():
        return exact
    for back in range(idx - 1, 0, -1):
        fallback = BASELINE_IMAGE_ROOT / system / "images" / f"{game_id}_seg_{back:03d}.png"
        if fallback.exists():
            return fallback
    return None


def copy_image(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    rel = dst.relative_to(SITE_ASSETS_ROOT.parent).as_posix()
    return f"/{rel}"


def build_cdn_url(base_url: str, theme_id: str, branch: str, system: str, idx: int) -> str:
    prefix = base_url.rstrip("/")
    return f"{prefix}/themes/{theme_id}/{branch}/{system}/seg_{idx:03d}.png"


def build_image_candidates(theme_id: str, game_id: str, segments: int, assets_base_url: str | None) -> list[dict] | None:
    candidates = []
    for system in IMAGE_SYSTEMS:
        image_urls: list[str] = []
        for idx in range(1, segments + 1):
            if system == "dn":
                src = THEME_ROOT / theme_id / f"{game_id}_{idx:03d}.png"
            else:
                src = resolve_baseline_image(system, game_id, idx)
            if src is None or not src.exists():
                return None
            if assets_base_url:
                image_urls.append(build_cdn_url(assets_base_url, theme_id, "image", system, idx))
            else:
                dst = SITE_ASSETS_ROOT / theme_id / "image" / system / f"seg_{idx:03d}.png"
                image_urls.append(copy_image(src, dst))
        candidates.append({"system": system, "images": image_urls})
    return candidates


def build_text_candidates(
    theme_id: str, game_id: str, dn_segments: list[str], segments: int, assets_base_url: str | None
) -> list[dict] | None:
    theme_numeric_id = theme_id.split("_")[1]
    doc_segments = load_doc_story_segments(theme_numeric_id, segments)
    if doc_segments is None:
        return None

    dn_images: list[str] = []
    for idx in range(1, segments + 1):
        src = THEME_ROOT / theme_id / f"{game_id}_{idx:03d}.png"
        if not src.exists():
            return None
        if assets_base_url:
            dn_images.append(build_cdn_url(assets_base_url, theme_id, "text_ref", "dn", idx))
        else:
            dst = SITE_ASSETS_ROOT / theme_id / "text_ref" / "dn" / f"seg_{idx:03d}.png"
            dn_images.append(copy_image(src, dst))

    return [
        {"system": "dn_text", "textSegments": dn_segments, "images": dn_images},
        {"system": "doc_text", "textSegments": doc_segments, "images": dn_images},
    ]


def build_theme(theme_dir: Path, segments: int, assets_base_url: str | None) -> dict | None:
    theme_id = theme_dir.name
    parts = theme_id.split("_")
    if len(parts) < 4:
        return None
    game_id = f"game_{'_'.join(parts[3:])}"

    dn_story = load_dn_story_segments(theme_dir, game_id, segments)
    if dn_story is None:
        return None

    image_candidates = build_image_candidates(theme_id, game_id, segments, assets_base_url)
    if image_candidates is None:
        return None

    text_candidates = build_text_candidates(theme_id, game_id, dn_story, segments, assets_base_url)
    if text_candidates is None:
        return None

    title = f"{theme_id} | {clip_preview(dn_story[0])}"
    image_case = {
        "id": f"{theme_id}_image",
        "title": title,
        "storySegments": dn_story,
        "candidates": image_candidates,
    }
    text_case = {
        "id": f"{theme_id}_text",
        "title": title,
        "storySegments": dn_story,
        "candidates": text_candidates,
    }
    return {"themeId": theme_id, "title": title, "imageCase": image_case, "textCase": text_case}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build theme catalog for DN human eval.")
    parser.add_argument("--segments", type=int, default=10, help="Number of segments per theme.")
    parser.add_argument("--max-themes", type=int, default=10, help="How many themes to include.")
    parser.add_argument(
        "--assets-base-url",
        default="",
        help="Optional CDN prefix, e.g. https://sen-illion.com/dn-eval-assets . If set, catalog uses CDN URLs.",
    )
    args = parser.parse_args()

    assets_base_url = args.assets_base_url.strip()
    if not assets_base_url:
        if SITE_ASSETS_ROOT.exists():
            shutil.rmtree(SITE_ASSETS_ROOT)

    themes: list[dict] = []
    for theme_dir in sorted(THEME_ROOT.glob("theme_*_game_*")):
        built = build_theme(theme_dir, args.segments, assets_base_url if assets_base_url else None)
        if built:
            themes.append(built)
        if len(themes) >= args.max_themes:
            break

    if len(themes) < args.max_themes:
        raise SystemExit(f"Only built {len(themes)} themes, expected {args.max_themes}. Check source datasets.")

    catalog = {
        "studyTitle": "DN 人类评测",
        "instructionsByMode": {
            "text": [
                "请按段阅读两套匿名文本，重点关注文本一致性、可读性和叙事连贯性。",
                "同一段会提供参考配图，图片仅用于帮助理解场景，不作为文本优劣唯一依据。",
            ],
            "image": [
                "请按段查看同一文本下的多套匿名图片，比较其图文一致性与跨段连续性。",
                "每一段都展示对应段落文本，请结合该段文本再评分。",
            ],
        },
        "dimensionsByMode": {"text": TEXT_DIMENSIONS, "image": IMAGE_DIMENSIONS},
        "themes": themes,
    }

    SITE_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    out = SITE_DATA_ROOT / "theme_catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(themes)} themes to {out}")


if __name__ == "__main__":
    main()
