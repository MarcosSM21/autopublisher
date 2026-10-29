# Quickstart: validar Analytics & Performance (Feature 027)

## Tests dirigidos (offline, con gateways falsos)

```bash
cd backend
uv run pytest tests/test_analytics_*.py -q
cd ../frontend
npm test -- src/pages/analytics
```

Cobertura esperada por checkpoint: ver [plan.md §Checkpoints](plan.md).

## Validación real (instancia segura)

Usar siempre una copia aislada (`AUTOPUBLISHER_CONFIG` hacia una config de prueba y el keyring
que falla), según la práctica del proyecto. Para leer métricas reales hace falta una cuenta de
YouTube o Instagram conectada en esa instancia.

1. Arrancar backend y frontend; abrir `Proyecto → Analytics`.
2. **Capacidades**: YouTube `supported`; Instagram `basic` supported e `insights`
   `permission_required`; Threads `permission_required`; TikTok "no soportada en esta
   versión"; Telegram "no soportada en esta versión".
3. **Refresco manual** de un vídeo de YouTube ya publicado → en menos de 1 minuto aparecen
   `viewCount`, `likeCount` y `commentCount` con fecha de obtención y engagement con fórmula y
   componentes. Repetirlo antes de 15 minutos → mensaje de cooldown con la hora disponible.
4. **Instagram**: tras refrescar se ven `like_count` y `comments_count`; el panel de
   capacidades indica "Insights: permission needed" y no hay views ni engagement.
5. **Publicación sin ID** (TikTok inbox o Instagram con `remote_identity_unavailable`) →
   "sin vínculo remoto" con el motivo; nunca 0.
6. **Prioridad**: programar una publicación a 5 minutos y pedir un refresco de proyecto → las
   lecturas esperan hasta que la publicación termina.
7. **Ranking y por tipo**: con una cuenta de YouTube seleccionada, ordenar por `viewCount`; los
   posts sin la métrica quedan en "Not ranked". Sin cuenta seleccionada, el control de orden
   está deshabilitado. El resumen por tipo muestra medianas o "Insufficient sample" (< 3).
8. **Lado a lado**: un media publicado en YouTube e Instagram muestra likes y comments
   alineados con su nombre original y la nota de no equivalencia; views solo en YouTube; sin
   totales.
9. **Evolución**: tras dos refrescos, "Evolution" de la publicación muestra dos puntos reales
   unidos por una línea discontinua y la tabla con la hora exacta de cada lectura.

## Checks de cierre (una vez, antes del PR)

`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`; frontend `npm run lint`,
`npm run format:check`, `npm run typecheck`, `npm run build`; y
`git diff --check`.
