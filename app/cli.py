"""CLI интерфейс."""
import argparse
import asyncio
import sys
from pathlib import Path

from .api import _process_job
from .config import settings
from . import storage


async def transcribe_cmd(file_path: str, prompt: str, model: str):
    p = Path(file_path)
    if not p.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    import uuid
    job_id = f"mp-{uuid.uuid4().hex[:12]}"
    mime = "video/" if p.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv") else "audio/"
    kind = "video" if mime.startswith("video/") else "audio"
    storage.init_db()
    storage.create_job(
        job_id=job_id,
        model_used=model,
        is_video=(kind == "video"),
        file_name=p.name,
        file_path=str(p),
    )
    print(f"Job: {job_id}")
    print("Processing...")
    await _process_job(job_id, p, prompt, model, kind)
    job = storage.get_job(job_id)
    if job and job.status == "completed":
        print(f"✓ Completed. DOCX: /api/v1/download/{job_id}.docx")
        print(f"  Protocol: {job.protocol.model_dump() if job.protocol else None}")
    else:
        print(f"✗ Failed: {job.error if job else 'unknown'}")


def main():
    p = argparse.ArgumentParser(prog="meeting-protocol")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribe", help="Обработать файл")
    t.add_argument("file", help="Путь к аудио/видео файлу")
    t.add_argument("--prompt", default="", help="Заметки к встрече")
    t.add_argument(
        "--model",
        default="minimax",
        choices=["m3", "minimax", "ollama"],
        help="LLM (default: minimax)",
    )

    sub.add_parser("list", help="Список завершённых протоколов")

    args = p.parse_args()
    if args.cmd == "transcribe":
        asyncio.run(transcribe_cmd(args.file, args.prompt, args.model))
    elif args.cmd == "list":
        storage.init_db()
        for j in storage.list_jobs():
            print(f"{j.job_id}\t{j.created_at}\t{j.file_name}")


if __name__ == "__main__":
    main()
