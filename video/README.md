# HackAlem AI — вступительный ролик

15.00 с · 1920×1080 · 30 fps · 150 BPM · стерео 48 кГц. Концепция «Разрешение»: *идея — один грубый пиксель; команда повышает разрешение, пока не проступит агент, и свет вырывается наружу.*
Подробно: `docs/02_concepts.md` (три концепции и выбор), `docs/03_script_and_art_direction.md` (сценарий, арт-дирекшн), `docs/04_sound.md` (звук), `docs/05_qc.md` (проверка результата).

## Что здесь лежит

```
index.html            композиция HyperFrames (корень, холст 1920×1080, аудио-дорожка)
src/hk-engine.js      рендер: функция drawFrame(t) — чистая функция времени (canvas 2D)
config/cues.json      ЕДИНЫЙ источник: тексты, палитра, все тайминги (картинка и звук читают его)
config/cues.js        сгенерирован из cues.json (npm run cues) — руками не править
assets/brand/         оригинальный logo.svg с hackalem.ai (не перерисован) и битовая карта знака 16×16
assets/fonts/         Manrope, JetBrains Mono (OFL, с hackalem.ai; кириллица + латиница)
assets/vendor/        GSAP 3.14.2 (локальная копия, чтобы рендер не ходил в сеть)
assets/audio/         hackalem-intro-mix.wav — синтезированный звук (audio/build_audio.py)
audio/build_audio.py  синтез звука «с нуля» (Python + numpy), читает config/cues.json
scripts/              build-cues, snap (кадры из движка), cover (обложка), sheet (контактный лист)
docs/                 исследование, концепции, сценарий, звук, проверка
renders/              результат (черновики не коммитятся)
```

## Воспроизвести рендер

Требования: Node ≥ 22, FFmpeg, интернет только для первой загрузки `hyperframes` и Chrome Headless Shell.

```bash
cd video
npx --yes hyperframes@0.8.143 browser ensure      # один раз: Chrome Headless Shell
npm run check                                     # lint + runtime + layout + motion + contrast
npm run render:final                              # → renders/hackalem-intro.mp4 (видео + звук)
npm run render:silent                             # → renders/hackalem-intro-silent.mp4 (та же видеодорожка, без звука)
npm run cover                                     # → renders/hackalem-intro-cover.png (1920×1080)
```

Версия `hyperframes` зафиксирована (0.8.143), чтобы рендер повторялся.

## Как редактировать

| Что менять | Где |
|---|---|
| Слова «ИДЕЯ / КОМАНДА / АГЕНТ», подпись счётчика, строка под лого | `config/cues.json → text`, затем `npm run cues` |
| Цвета | `config/cues.json → palette`, затем `npm run cues` |
| Моменты на таймлайне (удары, резка, отсчёт, печать лого…) | `config/cues.json → T` (секунды; сетка: шестнадцатая = 0.1 с = 3 кадра), затем `npm run cues` и `npm run audio` |
| Звук | `audio/build_audio.py` (читает те же времена), затем `npm run audio` |
| Длительность | `data-duration` в `index.html` + `meta.duration` в cues.json + длина аудио (build_audio.py) |
| Логотип | заменить `assets/brand/hackalem-logo.svg`; геометрию лок-апа (`K`, `WM_*`, `DOT`) править в `src/hk-engine.js` |

Быстрый просмотр отдельных кадров без полного рендера: `node scripts/snap.mjs out 0 0.5 9.6 10.3` → PNG в `out/`.
Для интерактивного монтажа: `npm run dev` (Studio HyperFrames).

## Источники и права

| Материал | Источник | Лицензия / примечание |
|---|---|---|
| Логотип `hackalem.ai`, цвета, шрифты | https://hackalem.ai (`/logo.svg`, CSS) | Бренд HackAlem AI; используется оригинальный вектор без изменений. Правил использования логотипа на сайте нет |
| Manrope, JetBrains Mono | файлы `woff2` с hackalem.ai | SIL Open Font License 1.1 |
| GSAP 3.14.2 | npm `gsap` | Лицензия GSAP (бесплатна для использования) |
| Рендер | HyperFrames 0.8.143 (HeyGen) | Apache-2.0 |
| Звук | синтезирован с нуля в `audio/build_audio.py` | Сэмплов и чужой музыки нет; права принадлежат автору проекта |
| Партнёрские логотипы, даты, суммы | не используются | Факты расходятся в источниках — см. `docs/01_research.md` |

## Проверка

Итоговый файл измерен и проверен — см. `docs/05_qc.md` (громкость −14.6 LUFS / true peak −1.6 dBTP, синхронизация, отсутствие чёрных/замороженных кадров, воспроизводимость рендера из архива). `python3 scripts/qc.py renders/hackalem-intro.mp4 renders/hackalem-intro-silent.mp4` повторяет автоматические проверки.
