# HackAlem AI — вступительный ролик, версия 2 «Сборка»

15.00 с · 1920×1080 · 30 fps · стерео 48 кГц. *Идея → Команда → Агент: 173 стеклянных куба складываются в слова, затем в знак бренда; удар света через вырезанную фигуру; лок-ап «HackAlem AI».*
Подробно: `docs/02_diagnosis_and_concept.md` (почему v1 получил 5.5/10 и что сделано), `docs/03_storyboard_and_art_direction.md` (сценарий по таймкодам, арт-дирекшн, реализация), `docs/04_sound.md` (звук), `docs/05_qc.md` (проверка результата и независимая критика), `docs/01_research.md` (бренд и проверка фактов).

## Что здесь лежит

```
index.html            композиция HyperFrames: холст WebGL 1920×1080, DOM-оверлей (логотип в углу, заголовок, строка), аудио-дорожка
src/main.js           камера, интенсивности света/пост-эффектов, DOM-оверлей; слушает hf-seek
src/world.js          Three.js: материал куба, среда, свет, фон, луч, пыль, тени-лучи через вырез знака, пост-цепочка
src/schedule.js       хореография: для каждого куба и времени t — позиция, поворот, масштаб, свечение (чистая функция)
src/glyphs.js         пиксельный шрифт 5×7 для ИДЕЯ / КОМАНДА / АГЕНТ и раскладка знака 16×16
config/cues.json      ЕДИНЫЙ источник: тексты, палитра, тайминги (картинка и звук читают его)
config/cues.js        сгенерирован (npm run cues), config/events.json — моменты посадок/букв для звука
assets/brand/         оригинальный logo.svg с hackalem.ai (не перерисован), hackalem-mark.svg (его же 173 пути), mark_grid.json
assets/fonts/         Manrope, JetBrains Mono (OFL)
assets/vendor/        GSAP 3.14.2, Three.js r170 (+ аддоны), лицензии рядом
assets/audio/         hackalem-intro-mix.wav (результат audio/build_audio.py)
audio/                build_audio.py + dsp.py, samples/ (7 CC0-файлов Kenney + SAMPLES_LICENSES.json), events_manifest.json
scripts/              build-cues/build-events, snap (кадры из движка), qc.py, motion_profile.py, sheet.py, montage.py, package.sh
docs/                 исследование, диагноз и концепция, сценарий, звук, проверка
renders/              результат (черновики не коммитятся)
```

## Воспроизвести рендер

Требования: Node ≥ 22, FFmpeg, Python 3 (numpy, scipy, soundfile, pedalboard — только для пересборки звука), интернет — только для первой загрузки `hyperframes` и Chrome Headless Shell. Рендер идёт на CPU (SwiftShader), ≈ 25–35 минут на 4 ядрах.

```bash
cd video
npx --yes hyperframes@0.8.143 browser ensure      # один раз
npm run check                                     # lint + runtime + layout + motion + contrast
npm run render:final                              # = hyperframes@0.8.143 render --quality delivery --output renders/hackalem-intro.mp4
npm run render:silent                             # та же видеодорожка без звука (ffmpeg -c:v copy -an)
python3 scripts/qc.py renders/hackalem-intro.mp4 renders/hackalem-intro-silent.mp4
```

Версия `hyperframes` зафиксирована (0.8.143). Звук: `npm run cues && npm run audio` (детерминирован; `HK_NO_SAMPLES=1` — только синтез).
Кадры без полного рендера: `node scripts/snap.mjs out 0 2.2 8.4 14` → PNG (то же ядро; без `SAMPLES=1` включается размытие движения, с ним — быстрее).

## Как редактировать

| Что менять | Где |
|---|---|
| Тексты слов, заголовка и строки | `config/cues.json → text`; слова из кубов — только буквы из `src/glyphs.js` (добавьте глифы 5×7 для новых) |
| Тайминги слов, сборки знака, вдоха, удара, глайда, заголовка | `config/cues.json → T`, затем `npm run cues` и `npm run audio` |
| Камера | массив `CAM` в `src/main.js` (время, дистанция, поворот, высота) |
| Свет, цвета, материал | `src/world.js` (материал куба, среда, фон); интенсивности по времени — `setScene` в `src/main.js` |
| Положение знака и размер лок-апа | `config/cues.json → lockup`; сетка заголовка/строки — `#title/#rule/#tagline` в `index.html` + `layoutOverlay` |
| Звук | `audio/build_audio.py` (аккорды `CHORDS`, уровни `gain=`, `PRE_DB`) |
| Логотип | заменить `assets/brand/hackalem-logo.svg`; `hackalem-mark.svg` — его 173 синих пути; `markGrid` — `assets/brand/mark_grid.json` |

## Источники и права

| Материал | Источник | Лицензия / примечание |
|---|---|---|
| Логотип `hackalem.ai`, цвета, шрифты | https://hackalem.ai | Бренд HackAlem AI; оригинальный вектор без изменений; `hackalem-mark.svg` — вынутые из него 173 пути |
| Manrope, JetBrains Mono | woff2 с hackalem.ai | SIL OFL 1.1 |
| Three.js r170 | npm `three` | MIT (`assets/vendor/three/LICENSE`) |
| GSAP 3.14.2 | npm `gsap` | Лицензия GSAP (бесплатна для использования) |
| Рендер | HyperFrames 0.8.143 (HeyGen) | Apache-2.0 |
| Звук | синтез в `audio/build_audio.py` + 7 CC0-семплов Kenney | Kenney CC0 1.0; учёт — `audio/samples/SAMPLES_LICENSES.json` |
| Даты, суммы, партнёрские логотипы | не используются | Факты расходятся — `docs/01_research.md` |

## Честно о проверке

Видео не просматривалось в реальном темпе, звук не прослушивался (в среде нет воспроизведения). Проверка — покадровые серии и контактные листы, измерения готового MP4 (`scripts/qc.py`), измерения звука (`eval_audio.py`: DSP против 43 реальных отрывков + ML-«слушатели» как детекторы поломок) и независимые критики-субагенты (два раунда, см. `docs/05_qc.md`).
