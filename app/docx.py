"""DOCX-генерация: HTML → DOCX через LibreOffice (soffice --headless)."""
import asyncio
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from .config import settings
from .models import Protocol

logger = logging.getLogger(__name__)


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _nl2br(s: str) -> str:
    return _esc(s).replace("\n", "<br/>")


def render_html(protocol: Protocol, job_id: str) -> str:
    """Рендерит протокол в HTML по утверждённому шаблону."""
    p = protocol
    html_parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Протокол встречи</title>',
        "<style>",
        "body{font-family:'Times New Roman',serif;font-size:12pt;max-width:800px;margin:2em auto;line-height:1.4;}",
        "h1{text-align:center;font-size:18pt;margin-bottom:0.3em;}",
        ".meta{text-align:center;margin-bottom:1.5em;}",
        ".meta b{font-weight:bold;}",
        "h2{font-size:13pt;margin-top:1.2em;border-bottom:1px solid #999;padding-bottom:2px;}",
        ".item{margin:0.5em 0;}",
        ".item-title{font-weight:bold;}",
        ".sub{margin-left:1.5em;color:#222;}",
        ".due{font-weight:bold;}",
        ".footer{text-align:right;font-style:italic;font-size:10pt;margin-top:2em;color:#666;}",
        "</style></head><body>",
        "<h1>ПРОТОКОЛ ВСТРЕЧИ</h1>",
    ]

    if p.date or p.time_start:
        html_parts.append('<div class="meta">')
        if p.date:
            html_parts.append(f"<div><b>Дата проведения:</b> {_esc(p.date)}</div>")
        if p.time_start:
            html_parts.append(f"<div><b>Время начала:</b> {_esc(p.time_start)}</div>")
        html_parts.append("</div>")

    if p.participants:
        html_parts.append("<h2>Участники</h2>")
        html_parts.append(f"<div>{_nl2br(p.participants)}</div>")

    if p.agenda:
        html_parts.append("<h2>Общая тема / повестка встречи</h2>")
        html_parts.append(f"<div>{_nl2br(p.agenda)}</div>")

    if p.questions:
        html_parts.append("<h2>Обсудили на встрече</h2>")
        for q in p.questions:
            html_parts.append(
                f'<div class="item"><span class="item-title">{_esc(q.q_number)}. '
                f"{_esc(q.q_title)}</span>"
            )
            if q.q_summary:
                html_parts.append(f'<div class="sub">{_nl2br(q.q_summary)}</div>')
            html_parts.append("</div>")

    if p.decisions:
        html_parts.append("<h2>Принятые решения</h2>")
        for d in p.decisions:
            html_parts.append(
                f'<div class="item"><span class="item-title">{_esc(d.d_number)}. '
                f"{_esc(d.d_text)}</span>"
            )
            owner_due = []
            if d.d_owner:
                owner_due.append(_esc(d.d_owner))
            if d.d_due:
                owner_due.append(f"срок: {_esc(d.d_due)}")
            if owner_due:
                html_parts.append(
                    f'<div class="sub">Ответственный: {", ".join(owner_due)}</div>'
                )
            html_parts.append("</div>")

    if p.open_questions:
        html_parts.append("<h2>Открытые вопросы</h2>")
        for o in p.open_questions:
            html_parts.append(
                f'<div class="item"><span class="item-title">{_esc(o.o_number)}. '
                f"{_esc(o.o_text)}</span>"
            )
            if o.o_owner:
                html_parts.append(
                    f'<div class="sub">Ответственный: {_esc(o.o_owner)}</div>'
                )
            if o.o_due:
                html_parts.append(f'<div class="sub due">Срок: {_esc(o.o_due)}</div>')
            html_parts.append("</div>")

    now = datetime.now()
    file_created_at = now.strftime("%d.%m.%Y %H:%M")
    html_parts.append(
        f'<div class="footer">Дата создания файла: {file_created_at}</div>'
    )
    html_parts.append("</body></html>")
    return "".join(html_parts)


async def html_to_docx(html: str, out_path: Path) -> Path:
    """Конвертирует HTML в DOCX через LibreOffice.

    LibreOffice создаёт файл с тем же basename что и источник, но расширением .docx.
    Поэтому передаём временный .html файл, а потом переименовываем результат.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # LibreOffice: source=html, target=docx. Имя выходного файла = basename(source) + .docx.
    html_path = out_path.with_name(out_path.stem + ".html")
    html_path.write_text(html, encoding="utf-8")

    # Используем явный фильтр MS Word 2007 XML, иначе HTML опознаётся как
    # Writer/Web и не имеет docx export filter (LibreOffice 24.x).
    cmd = [
        settings.soffice_path,
        "--headless",
        "--convert-to", "docx:MS Word 2007 XML",
        "--outdir", str(out_path.parent),
        str(html_path),
    ]
    logger.info(f"DOCX: запуск soffice: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    # Удаляем временный html
    html_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"soffice failed ({proc.returncode}): {stderr.decode()[:500]}"
        )

    # LibreOffice создал файл с тем же basename + .docx
    soffice_output = out_path.with_name(out_path.stem + ".docx")
    if not soffice_output.exists():
        raise RuntimeError(
            f"DOCX не создан: ожидался {soffice_output}, soffice stderr={stderr.decode()[:300]}"
        )

    # Если целевой путь отличается — переименовываем
    if soffice_output != out_path:
        soffice_output.rename(out_path)

    return out_path


async def render_protocol_docx(
    protocol: Protocol, job_id: str, output_name: str | None = None
) -> Path:
    """Полный пайплайн: HTML → DOCX. Возвращает путь к файлу.

    output_name: желаемое имя файла без .docx (по умолчанию — job_id).
    """
    html = render_html(protocol, job_id)
    base = output_name or job_id
    out_path = settings.storage_dir / "protocols" / f"{base}.docx"
    return await html_to_docx(html, out_path)
