from __future__ import annotations

import json
import os
import secrets
import threading
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import oss2
from flask import Flask, jsonify, request, send_file, send_from_directory


CURRENT_DIR = Path(__file__).resolve().parent
if (CURRENT_DIR / "index.html").exists():
    SITE_ROOT = CURRENT_DIR
    REPO_ROOT = CURRENT_DIR.parent if (CURRENT_DIR.parent / "outputs").exists() else CURRENT_DIR
else:
    REPO_ROOT = CURRENT_DIR.parent
    SITE_ROOT = REPO_ROOT / "human_eval_site"

DATA_ROOT = SITE_ROOT / "data"
RESULTS_ROOT = SITE_ROOT / "collected_results"
THEME_CATALOG_PATH = DATA_ROOT / "theme_catalog.json"
INVITE_TOKENS_PATH = DATA_ROOT / "invite_tokens.json"
WRITE_LOCK = threading.Lock()
_OSS_BUCKET: oss2.Bucket | None = None

app = Flask(__name__, static_folder=str(SITE_ROOT), static_url_path="")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize_segment(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return cleaned.strip("_") or "unknown"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_theme_catalog() -> dict[str, Any]:
    catalog = load_json(THEME_CATALOG_PATH, {})
    if not catalog or not catalog.get("themes"):
        raise FileNotFoundError("theme_catalog.json is missing. Run human_eval_site/tools/build_theme_catalog.py first.")
    return catalog


def load_invites() -> dict[str, Any]:
    invites = load_json(INVITE_TOKENS_PATH, {})
    if not invites or not invites.get("tokens"):
        raise FileNotFoundError("invite_tokens.json is missing. Run human_eval_site/tools/generate_invites.py first.")
    return invites


def get_dataset_for_theme(theme_id: str, mode: str) -> dict[str, Any]:
    catalog = load_theme_catalog()
    mode_key = "text" if mode == "text" else "image"
    case_key = "textCase" if mode_key == "text" else "imageCase"
    for theme in catalog["themes"]:
        if theme.get("themeId") == theme_id:
            selected_case = theme.get(case_key) or theme.get("case")
            if not selected_case:
                raise KeyError(f"Theme {theme_id} has no case for mode {mode_key}")
            return {
                "studyTitle": catalog.get("studyTitle", "DN 人类评测"),
                "mode": mode_key,
                "instructions": (catalog.get("instructionsByMode", {}) or {}).get(mode_key, []),
                "dimensions": (catalog.get("dimensionsByMode", {}) or {}).get(mode_key, []),
                "cases": [selected_case],
            }
    raise KeyError(f"Unknown theme: {theme_id}")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def get_oss_bucket() -> oss2.Bucket | None:
    global _OSS_BUCKET
    if _OSS_BUCKET is not None:
        return _OSS_BUCKET

    endpoint = str(os.environ.get("OSS_ENDPOINT") or "").strip()
    bucket_name = str(os.environ.get("OSS_BUCKET") or "").strip()
    access_key_id = str(os.environ.get("OSS_ACCESS_KEY_ID") or "").strip()
    access_key_secret = str(os.environ.get("OSS_ACCESS_KEY_SECRET") or "").strip()

    if not (endpoint and bucket_name and access_key_id and access_key_secret):
        return None

    auth = oss2.Auth(access_key_id, access_key_secret)
    _OSS_BUCKET = oss2.Bucket(auth, endpoint, bucket_name)
    return _OSS_BUCKET


def upload_submission_to_oss(submission_record: dict[str, Any], result_path: Path) -> str | None:
    bucket = get_oss_bucket()
    if bucket is None:
        return None

    prefix = str(os.environ.get("OSS_RESULTS_PREFIX") or "dn-eval-submissions").strip().strip("/")
    if not prefix:
        prefix = "dn-eval-submissions"

    rel_path = result_path.relative_to(RESULTS_ROOT).as_posix()
    object_key = f"{prefix}/{rel_path}"
    payload = json.dumps(submission_record, ensure_ascii=False, indent=2).encode("utf-8")
    bucket.put_object(object_key, payload)

    public_base = str(os.environ.get("OSS_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if public_base:
        return f"{public_base}/{object_key}"
    return f"oss://{bucket.bucket_name}/{object_key}"


def get_admin_export_key() -> str:
    return str(os.environ.get("HUMAN_EVAL_ADMIN_KEY") or os.environ.get("EXPORT_RESULTS_KEY") or "").strip()


def request_admin_key() -> str:
    bearer_prefix = "Bearer "
    auth_header = str(request.headers.get("Authorization") or "").strip()
    if auth_header.startswith(bearer_prefix):
        return auth_header[len(bearer_prefix) :].strip()
    return str(request.headers.get("X-Admin-Key") or request.args.get("key") or "").strip()


def require_admin_export_key():
    expected_key = get_admin_export_key()
    if not expected_key:
        return jsonify({"error": "Admin export is disabled. Set HUMAN_EVAL_ADMIN_KEY in Render environment variables."}), 503
    if not secrets.compare_digest(request_admin_key(), expected_key):
        return jsonify({"error": "Unauthorized"}), 401
    return None


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Admin-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/api/session", methods=["GET", "OPTIONS"])
def session():
    if request.method == "OPTIONS":
        return ("", 204)

    token = str(request.args.get("token") or "").strip()
    if not token:
        return jsonify({"error": "Missing token"}), 400

    query_mode = str(request.args.get("mode") or "").strip().lower()
    try:
        invites = load_invites()
        assignment = None
        for item in invites["tokens"]:
            if item.get("token") == token:
                assignment = item
                break
        if assignment is None:
            raise KeyError(f"Unknown token: {token}")

        effective_mode = str(assignment.get("mode") or query_mode or "image").strip().lower()
        if effective_mode not in {"image", "text"}:
            effective_mode = "image"
        assignment["mode"] = effective_mode
        dataset = get_dataset_for_theme(str(assignment["themeId"]), effective_mode)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 500
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404

    if not assignment.get("claimedAt"):
        assignment["claimedAt"] = utc_now_iso()
        save_json(INVITE_TOKENS_PATH, invites)

    return jsonify(
        {
            "assignment": {
                "token": assignment.get("token"),
                "themeId": assignment.get("themeId"),
                "themeTitle": assignment.get("themeTitle"),
                "batchId": assignment.get("batchId"),
                "mode": assignment.get("mode", "image"),
                "slotIndex": assignment.get("slotIndex"),
                "claimedAt": assignment.get("claimedAt"),
                "submittedAt": assignment.get("submittedAt"),
                "submissionCount": assignment.get("submissionCount", 0),
                "evaluatorId": assignment.get("evaluatorId", ""),
            },
            "dataset": dataset,
        }
    )


@app.route("/api/submit", methods=["POST", "OPTIONS"])
def submit():
    if request.method == "OPTIONS":
        return ("", 204)

    body = request.get_json(silent=True) or {}
    token = str(body.get("token") or "").strip()
    if not token:
        return jsonify({"error": "Missing token"}), 400

    evaluator_id = str(body.get("evaluatorId") or "").strip()
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return jsonify({"error": "Missing payload"}), 400

    try:
        catalog = load_theme_catalog()
        invites = load_invites()
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 500

    assignment = None
    for item in invites["tokens"]:
        if item.get("token") == token:
            assignment = item
            break
    if assignment is None:
        return jsonify({"error": f"Unknown token: {token}"}), 404

    theme_id = assignment.get("themeId") or payload.get("assignment", {}).get("themeId") or "unknown_theme"
    theme_title = assignment.get("themeTitle") or theme_id
    saved_at = utc_now_iso()

    submission_record = {
        "savedAt": saved_at,
        "token": token,
        "themeId": theme_id,
        "themeTitle": theme_title,
        "mode": assignment.get("mode", "image"),
        "evaluatorId": evaluator_id,
        "remoteAddr": request.headers.get("X-Forwarded-For", request.remote_addr),
        "userAgent": request.headers.get("User-Agent", ""),
        "payload": payload,
    }

    timestamp_label = saved_at.replace(":", "-")
    result_dir = RESULTS_ROOT / sanitize_segment(str(theme_id))
    result_path = result_dir / f"{timestamp_label}__{sanitize_segment(token)}.json"
    index_path = RESULTS_ROOT / "submissions_index.jsonl"
    summary_path = RESULTS_ROOT / "latest_submission_summary.json"

    with WRITE_LOCK:
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(submission_record, ensure_ascii=False, indent=2), encoding="utf-8")
        append_jsonl(
            index_path,
            {
                "savedAt": saved_at,
                "token": token,
                "themeId": theme_id,
                "themeTitle": theme_title,
                "mode": assignment.get("mode", "image"),
                "evaluatorId": evaluator_id,
                "file": display_path(result_path),
            },
        )

        assignment["claimedAt"] = assignment.get("claimedAt") or saved_at
        assignment["submittedAt"] = saved_at
        assignment["evaluatorId"] = evaluator_id
        assignment["submissionCount"] = int(assignment.get("submissionCount", 0)) + 1
        assignment["latestResultFile"] = display_path(result_path)
        save_json(INVITE_TOKENS_PATH, invites)

        save_json(
            summary_path,
            {
                "updatedAt": saved_at,
                "themeCount": len(catalog.get("themes", [])),
                "tokenCount": len(invites.get("tokens", [])),
                "submittedCount": sum(1 for item in invites["tokens"] if item.get("submittedAt")),
                "latestSubmission": {
                    "token": token,
                    "themeId": theme_id,
                    "themeTitle": theme_title,
                    "mode": assignment.get("mode", "image"),
                    "evaluatorId": evaluator_id,
                    "file": display_path(result_path),
                },
            },
        )
        try:
            remote_path = upload_submission_to_oss(submission_record, result_path)
            if remote_path:
                submission_record["remoteFile"] = remote_path
                result_path.write_text(json.dumps(submission_record, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # Keep local save path reliable even if OSS upload fails.
            pass

    return jsonify(
        {
            "ok": True,
            "savedAt": saved_at,
            "themeId": theme_id,
            "file": display_path(result_path),
            "remoteFile": submission_record.get("remoteFile"),
        }
    )


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "time": utc_now_iso()})


@app.route("/api/admin/export-results", methods=["GET", "OPTIONS"])
def export_results():
    if request.method == "OPTIONS":
        return ("", 204)

    auth_error = require_admin_export_key()
    if auth_error:
        return auth_error

    timestamp_label = utc_now_iso().replace(":", "-")
    archive = BytesIO()
    file_count = 0

    with WRITE_LOCK:
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            if RESULTS_ROOT.exists():
                for path in sorted(RESULTS_ROOT.rglob("*")):
                    if not path.is_file() or path.is_symlink():
                        continue
                    try:
                        arcname = path.relative_to(RESULTS_ROOT).as_posix()
                    except ValueError:
                        continue
                    zip_file.write(path, arcname)
                    file_count += 1

            if file_count == 0:
                zip_file.writestr("README.txt", "No result files were found in human_eval_site/collected_results.\n")

            zip_file.writestr(
                "EXPORT_MANIFEST.json",
                json.dumps(
                    {
                        "exportedAt": utc_now_iso(),
                        "resultsRoot": display_path(RESULTS_ROOT),
                        "fileCount": file_count,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

    archive.seek(0)
    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"human-eval-results-{timestamp_label}.zip",
    )


@app.route("/assets/<path:filename>", methods=["GET"])
def assets(filename: str):
    return send_from_directory(SITE_ROOT / "assets", filename)


@app.route("/outputs/<path:filename>", methods=["GET"])
def outputs(filename: str):
    return send_from_directory(REPO_ROOT / "outputs", filename)


@app.route("/data/<path:filename>", methods=["GET"])
def data_files(filename: str):
    return send_from_directory(DATA_ROOT, filename)


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(SITE_ROOT, "index.html")


@app.route("/<path:filename>", methods=["GET"])
def static_files(filename: str):
    target = SITE_ROOT / filename
    if target.exists() and target.is_file():
        return send_from_directory(SITE_ROOT, filename)
    return send_from_directory(SITE_ROOT, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
