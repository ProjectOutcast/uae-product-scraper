"""
UAE Baby Product Scraper — Web App
===================================
Flask web UI for scraping baby products from 22 UAE online retailers.
"""

import os
import json
import uuid
import time
import threading
import asyncio
import glob as globmod
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, Response, send_file

from retailers import get_scraper_registry
from main import run_all_scrapers
from exporter import export_combined_csv

app = Flask(__name__)

# ─── Job Storage ─────────────────────────────────────────────────────────────

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()

JOB_EXPIRY_HOURS = 2


def _job_meta_path(job_id):
    return os.path.join(TEMP_DIR, f"{job_id}_meta.json")


def _save_job_meta(job_id, meta):
    path = _job_meta_path(job_id)
    safe = {k: v for k, v in meta.items() if k != "created_at"}
    safe["created_at"] = meta.get("created_at", datetime.now()).isoformat()
    with open(path, "w") as f:
        json.dump(safe, f)


def _load_job_meta(job_id):
    path = _job_meta_path(job_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            meta = json.load(f)
        meta["created_at"] = datetime.fromisoformat(meta["created_at"])
        return meta
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _get_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if job:
        return job
    return _load_job_meta(job_id)


def cleanup_old_jobs():
    now = datetime.now()
    cutoff = now - timedelta(hours=JOB_EXPIRY_HOURS)

    with jobs_lock:
        expired = [
            jid for jid, job in jobs.items()
            if job.get("created_at", now) < cutoff
        ]
        for jid in expired:
            del jobs[jid]

    for meta_file in globmod.glob(os.path.join(TEMP_DIR, "*_meta.json")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(meta_file))
            if mtime < cutoff:
                job_id = os.path.basename(meta_file).replace("_meta.json", "")
                os.remove(meta_file)
                for f in globmod.glob(os.path.join(TEMP_DIR, f"{job_id}_*")):
                    os.remove(f)
        except OSError:
            pass


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/retailers")
def get_retailers():
    return jsonify({"retailers": sorted(get_scraper_registry().keys())})


@app.route("/api/product-scrape", methods=["POST"])
def start_product_scrape():
    cleanup_old_jobs()

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    keyword = data.get("keyword", "").strip()
    retailers = data.get("retailers", [])

    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400
    if not retailers:
        return jsonify({"error": "Select at least one retailer"}), 400

    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id,
        "status": "running",
        "progress": 0,
        "messages": [],
        "summary": None,
        "csv_filepath": None,
        "csv_filename": None,
        "error": None,
        "created_at": datetime.now(),
        # Skip / Stop controls
        "skip_retailer": False,   # set True to skip current retailer
        "stop_requested": False,  # set True to stop entire scrape
        "stopped_early": False,   # set after stop completes
    }

    with jobs_lock:
        jobs[job_id] = job

    thread = threading.Thread(
        target=_run_product_scrape_job,
        args=(job_id, keyword, retailers),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


def _run_product_scrape_job(job_id, keyword, retailers):
    def progress_callback(message, percent=None):
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["messages"].append(message)
                if percent is not None:
                    jobs[job_id]["progress"] = percent

    def should_stop():
        with jobs_lock:
            job = jobs.get(job_id)
            return job.get("stop_requested", False) if job else False

    def should_skip():
        """Check & consume the skip flag (returns True once, then resets)."""
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return False
            if job.get("skip_retailer"):
                job["skip_retailer"] = False  # consume the flag
                return True
            return False

    try:
        output_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(output_dir, exist_ok=True)

        products = asyncio.run(
            run_all_scrapers(
                retailers=retailers,
                headless=True,
                resume=False,
                output_dir=output_dir,
                keyword=keyword,
                progress_callback=progress_callback,
                should_stop=should_stop,
                should_skip=should_skip,
            )
        )

        was_stopped = should_stop()

        if products:
            csv_filename = f"{keyword.replace(' ', '_')}_products.csv"
            csv_path = os.path.join(TEMP_DIR, f"{job_id}_{csv_filename}")
            export_combined_csv(products, csv_path)

            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["progress"] = 100
                    jobs[job_id]["csv_filepath"] = csv_path
                    jobs[job_id]["csv_filename"] = csv_filename
                    jobs[job_id]["summary"] = {"total": len(products)}
                    jobs[job_id]["stopped_early"] = was_stopped
                    if was_stopped:
                        jobs[job_id]["messages"].append(
                            f"Stopped by user. Exported {len(products)} products collected so far."
                        )
                    else:
                        jobs[job_id]["messages"].append(
                            f"Done! Exported {len(products)} products to CSV."
                        )
                    _save_job_meta(job_id, jobs[job_id])
        else:
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["progress"] = 100
                    jobs[job_id]["summary"] = {"total": 0}
                    jobs[job_id]["stopped_early"] = was_stopped
                    if was_stopped:
                        jobs[job_id]["messages"].append("Stopped by user. No products were collected.")
                    else:
                        jobs[job_id]["messages"].append("No products found.")
                    _save_job_meta(job_id, jobs[job_id])

    except Exception as e:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e)
                jobs[job_id]["messages"].append(f"Error: {e}")
                _save_job_meta(job_id, jobs[job_id])


@app.route("/api/progress/<job_id>")
def stream_progress(job_id):
    def generate():
        last_msg_idx = 0
        last_progress = -1

        while True:
            with jobs_lock:
                job = jobs.get(job_id)

            if not job:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
                break

            messages = job.get("messages", [])
            while last_msg_idx < len(messages):
                msg = messages[last_msg_idx]
                last_msg_idx += 1
                yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"

            progress = job.get("progress", 0)
            if progress != last_progress:
                last_progress = progress
                yield f"data: {json.dumps({'type': 'progress', 'percent': progress})}\n\n"

            status = job.get("status")
            if status == "completed":
                result = {
                    "type": "completed",
                    "summary": job.get("summary"),
                    "has_file": job.get("csv_filepath") is not None,
                    "stopped_early": job.get("stopped_early", False),
                }
                yield f"data: {json.dumps(result)}\n\n"
                break
            elif status == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': job.get('error', 'Unknown error')})}\n\n"
                break

            time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/skip/<job_id>", methods=["POST"])
def skip_retailer(job_id):
    """Signal the scraper to skip the current retailer."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.get("status") != "running":
            return jsonify({"error": "Job not active"}), 404
        job["skip_retailer"] = True
    return jsonify({"ok": True})


@app.route("/api/stop/<job_id>", methods=["POST"])
def stop_scrape(job_id):
    """Signal the scraper to stop and export what it has so far."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.get("status") != "running":
            return jsonify({"error": "Job not active"}), 404
        job["stop_requested"] = True
    return jsonify({"ok": True})


@app.route("/api/download/<job_id>")
def download_file(job_id):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found. The file may have expired (files are kept for 2 hours)."}), 404

    filepath = job.get("csv_filepath")
    filename = job.get("csv_filename", "products.csv")

    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found. It may have been cleaned up. Please run the scrape again."}), 404

    return send_file(filepath, as_attachment=True, download_name=filename, mimetype="text/csv")


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
