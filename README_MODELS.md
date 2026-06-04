# Meeting-Protocol — Модели ASR

> ⛔ **Модели НЕ входят в git-репозиторий** (объяснение ниже).
> Скачиваются отдельно через `scripts/download_models.bat` (Windows)
> или вручную с huggingface.co (Linux).

---

## Почему не в репо

| Причина | Детали |
|---|---|
| **Размер** | `ggml-large-v3.bin` = 3.1 ГБ. С medium + base = ~4.7 ГБ |
| **GitHub LFS** | Бесплатный тариф = 1 ГБ. Платный = $5/мес за 50 ГБ |
| **Git clone** | Без LFS = скачает 4.7 ГБ как обычные blob'ы (медленно, ~30 мин) |
| **CI/CD** | 5 ГБ git history = 30+ минут на каждое `git pull` |
| **Диск разработчика** | Место на dev-машинах быстро заканчивается |

**Решение:** модели — в **отдельном репозитории** или на **GitHub Releases** (прямой скачиваемый URL с SHA256).

---

## Доступные модели

| ID | Файл | Размер | Скорость (CPU) | Скорость (GPU) | Качество | Рекомендация |
|---|---|---|---|---|---|---|
| `tiny` | `ggml-tiny.bin` | 39 МБ | ~30× realtime | ~300× realtime | ⭐⭐ | быстрые черновики, низкое качество |
| `base` | `ggml-base.bin` | 142 МБ | ~10× realtime | ~100× realtime | ⭐⭐⭐ | **по умолчанию** для быстрых встреч |
| `medium` | `ggml-medium.bin` | 1.5 ГБ | ~2× realtime | ~25× realtime | ⭐⭐⭐⭐ | хороший баланс |
| `large-v3` | `ggml-large-v3.bin` | 3.1 ГБ | ~0.5× realtime | ~10× realtime | ⭐⭐⭐⭐⭐ | максимальное качество |

`realtime` означает: 1 час аудио = N часов обработки. RTX 3060 обрабатывает 1 час за 6 минут на `large-v3`.

---

## SHA256 хэши (для проверки)

> ⚠️ Перед коммитом файла с реальными хэшами — пересчитайте:
> ```bash
> sha256sum ggml-base.bin
> ```

| Файл | SHA256 (placeholder) |
|---|---|
| `ggml-tiny.bin` | `be07e048e1f556af3a7d39f5ae2abd4b7bb1a17853c0f8ba7c2b0c5b3b3c7e1e` |
| `ggml-base.bin` | `c3ee50d9c5b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1` |
| `ggml-medium.bin` | `d3a4ee50d9c5b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1` |
| `ggml-large-v3.bin` | `e6b29fd97c5b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1` |

> Замените placeholder'ы на реальные после первого скачивания. Скрипт скачивания использует эти хэши.

---

## Скачивание

### Windows (после `install.bat`)

```cmd
REM Базовая модель (142 МБ) - по умолчанию
scripts\download_models.bat

REM Или конкретная
scripts\download_models.bat base
scripts\download_models.bat medium
scripts\download_models.bat large-v3

REM Или все сразу
scripts\download_models.bat all
```

Скрипт:
1. Создаёт папку `%ProgramFiles%\Meeting-Protocol\whisper.cpp\models` если её нет
2. Скачивает .bin с `huggingface.co/ggerganov/whisper.cpp`
3. Проверяет SHA256
4. Если хэш совпадает — пропускает повторное скачивание

### Linux (srv-ai1 / ваш сервер)

```bash
mkdir -p /opt/meeting-protocol/whisper.cpp/models
cd /opt/meeting-protocol/whisper.cpp/models

# base
wget https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
sha256sum ggml-base.bin
# Сравнить с хэшем выше
```

### Python (без whisper.cpp)

Если вы хотите использовать `openai-whisper` или `faster-whisper` вместо whisper.cpp:

```python
# faster-whisper (рекомендуется, в 4× быстрее openai-whisper)
pip install faster-whisper
python -c "from faster_whisper import WhisperModel; m = WhisperModel('base'); print('OK')"
```

Модели скачаются автоматически в `~/.cache/huggingface/`.

---

## Расположение на диске

### Windows (после `install.bat` + `download_models.bat base`)

```
C:\Program Files\Meeting-Protocol\whisper.cpp\models\
  ggml-base.bin         (142 MB)
```

Эту папку уже знает `whisper-server.exe` (запускается как Windows Service сразу после `install.bat`).

### Linux (рекомендуемый layout)

```
/opt/meeting-protocol/
  app/                   # исходники (из git clone)
  whisper.cpp/           # бинарь whisper-server (из winget / apt)
    models/
      ggml-base.bin
      ggml-large-v3.bin
```

### macOS

```
~/Meeting-Protocol/
  whisper.cpp/
    models/
```

---

## Обновление моделей

whisper.cpp обновляет модели раз в ~3-6 месяцев. Следить:
- [github.com/ggml-org/whisper.cpp/releases](https://github.com/ggml-org/whisper.cpp/releases)
- [huggingface.co/ggerganov/whisper.cpp/tree/main](https://huggingface.co/ggerganov/whisper.cpp/tree/main)

Обновить:
```cmd
scripts\download_models.bat base      # перекачает новую версию
```

---

## Альтернативы (без whisper.cpp)

| Движок | Модели | Установка | Плюсы |
|---|---|---|---|
| **openai-whisper** | `tiny/base/small/medium/large-v3` | `pip install openai-whisper` | оригинал, медленнее |
| **faster-whisper** | те же | `pip install faster-whisper` | в 4× быстрее, CTranslate2 |
| **whisper.cpp** (наш) | `ggml-*.bin` | winget/choco | быстрее всего, низкое потребление RAM |
| **OpenAI API** | `whisper-1` | `pip install openai` | облако, без GPU |

Все три локальных варианта используют **одни и те же обученные модели**, отличается только runtime. `ggml-base.bin` ≡ `base.pt` (только формат другой).

---

## Лицензия моделей

Все модели whisper — **MIT license** (открытый код, можно использовать в коммерческих продуктах). Скачивая, вы соглашаетесь с [условиями OpenAI](https://github.com/openai/whisper/blob/main/LICENSE).
