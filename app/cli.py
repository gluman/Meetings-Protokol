"""CLI интерфейс."""
import argparse
import asyncio
import sys
from pathlib import Path

from .api import _process_job
from . import storage


async def transcribe_cmd(file_path: str, prompt: str):
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
        model_used="m3",
        is_video=(kind == "video"),
        file_name=p.name,
        file_path=str(p),
    )
    print(f"Job: {job_id}")
    print("Processing (M3)...")
    # Glossary injection: _process_job сам подтянет entries через job_glossaries
    await _process_job(job_id, p, prompt, kind)
    job = storage.get_job(job_id)
    if job and job.status == "completed":
        print(f"✓ Completed. DOCX: /api/v1/download/{job_id}.docx")
        if job.protocol:
            print(f"  Protocol: {job.protocol.model_dump()}")
    else:
        print(f"✗ Failed: {job.error if job else 'unknown'}")


def main():
    p = argparse.ArgumentParser(prog="meeting-protocol")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribe", help="Обработать файл")
    t.add_argument("file", help="Путь к аудио/видео файлу")
    t.add_argument("--prompt", default="", help="Заметки к встрече")

    sub.add_parser("list", help="Список завершённых протоколов")

    args = p.parse_args()
    if args.cmd == "transcribe":
        asyncio.run(transcribe_cmd(args.file, args.prompt))
    elif args.cmd == "list":
        storage.init_db()
        for j in storage.list_jobs():
            print(f"{j.job_id}\t{j.created_at}\t{j.file_name}")


if __name__ == "__main__":
    main()
