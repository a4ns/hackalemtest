# HackAlem AI — вступительный ролик · сдача

| Файл | Что это |
|---|---|
| `hackalem-ai-intro.mp4` | **Финальный ролик со звуком.** 15.000 с, 1920×1080, 30 fps, H.264 High + AAC 192 кбит/с, −14.6 LUFS, true peak −1.6 dBTP |
| `hackalem-ai-intro-hq.mp4` | Тот же ролик, перекодированный для пересылки: 23 МиБ, CRF 18, звук без перекодирования |
| `hackalem-ai-intro-preview.mp4` | Лёгкая копия для просмотра в чате: 5.5 МБ, CRF 22, звук без перекодирования |
| `hackalem-ai-intro-silent.mp4` | Тот же ролик без звука — видеодорожка побитово та же (`-c:v copy`) |
| `hackalem-ai-intro-cover.png` | Обложка 1920×1080 (светящийся знак + «HackAlem AI» + строка) |
| `hackalem-ai-intro-project.zip` | Редактируемый проект целиком: исходники, оригинальный `logo.svg`, шрифты, синтез звука, скрипты, документы (без рендеров) |

Проект также лежит в `../video/` (там же `README.md` с инструкцией по редактированию и таблицей источников).

## Точная проверенная команда повторного рендера

```bash
cd video
npx --yes hyperframes@0.8.143 browser ensure      # один раз: Chrome Headless Shell
npm run check                                     # lint + runtime + layout + motion + contrast
npm run render:final                              # = npx hyperframes@0.8.143 render --quality delivery --output renders/hackalem-intro.mp4
npm run render:silent                             # версия без звука
npm run cover                                     # обложка
```

Звук пересобирается отдельно (детерминированно): `npm run cues && npm run audio`.
Проверено: архив распакован в другую папку, звук пересобран (sha256 WAV совпал), выполнены `check` и `render:final` — получился MP4, **побитово идентичный** этому (см. `video/docs/05_qc.md`).

## Документы (`video/docs/`)
`01_research.md` — бренд и проверка фактов · `02_concepts.md` — три концепции и выбор · `03_script_and_art_direction.md` — сценарий по таймкодам, арт-дирекшн, принятая критика · `04_sound.md` — звук · `05_qc.md` — проверка результата.

## Что нужно проверить человеку
Видео не просматривалось в реальном темпе и звук не прослушивался (в среде нет воспроизведения) — проверка шла по покадровым сериям и измерениям. Особенно стоит послушать баланс и тембры на реальных колонках.
