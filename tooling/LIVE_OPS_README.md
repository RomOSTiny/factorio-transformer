# Живые операции: сборка блока в Factorio через RCON

Скрипты `live_*.py` — рабочий конвейер постройки/ремонта больших блоков
(сохранены из scratchpad сессии 15.09.2026, чтобы пережили сессию).
Запускать python из `venv\Scripts\python.exe`, cwd = `tooling/`. Нужен запущенный
Factorio через "Host Saved Game" (RCON). Никаких `--` комментариев в Lua,
отправляемом по RCON (см. CLAUDE.md).

## Порядок для любого блока (СТРОГО последовательно, не повторять шаги)

1. Сгенерировать blueprint (`stage2_*_param.py` → `*_blueprint.txt` + `*_ids.json`).
   Офсет local→world = ЦЕНТР_ПОСТРОЙКИ − центр bbox по ВСЕМ сущностям из `*_ids.json`
   (включая подстанции).
2. Recon площадки (спавнеры блокируют build молча — сносить `type="unit-spawner"`
   можно), `request_to_generate_chunks` с достаточным радиусом (10).
3. `live_build_blueprint.py <bp.txt> <X> <Y> [chunk_radius]` — build_blueprint.
4. `live_revive_batched.py <X> <Y>` — revive батчами по ≤400 до 0 ghost
   (внутри зашиты HX,HY=280,440 — для другого размера править константы).
5. **entity-repair** `live_repair_entities.py <bp.txt> <OX> <OY> <CX> <CY> <HX> <HY>`
   ОДИН раз, дождаться `failed=0`. Блоки >~2000 сущностей ВСЕГДА теряют часть
   (LayerNorm 4507: детерминированно 244) — это нормально, чинится этим шагом.
6. **wire-repair** `live_repair_wires.py <те же аргументы>` ОДИН раз, ТОЛЬКО ПОСЛЕ
   шага 5. Не запускать «на всякий случай» и не повторять — иначе возможна
   постоянная ложная связь (кратные значения на выходе); лечится только сносом
   блока и пересборкой (случай LN_ffn, Решение 41).
7. **power-repair** `live_repair_power.py <CX> <CY> <HX> <HY>` (revive не соединяет
   подстанции). EEI (`electric-energy-interface`) для matmul/LN-генераторов уже
   строится сам (исправлено в `matmul_gen_lib.py`); старые постройки создавали вручную.
8. `live_reset_ln_counters_latches.py <OX> <OY>` (LayerNorm-геометрия) —
   сбросить свободнобегущие счётчики И latch-аккумуляторы ОДНОВРЕМЕННО, затем
   `live_wait_ln_sweep.py <x> <y> 2450` (ждёт свип), читать `*lat_*` выходы.

Чтение выходов: `get_signals(combinator_output_red[, _green])` на самом
комбинаторе-латче; для ConstantCombinator — `circuit_red/circuit_green`.
Чтение сразу двух цветов на сущности, выход которой разведён на оба цвета к
разным потребителям, ДВОИТ значение (артефакт диагностики, не баг схемы).

## Сборка блоков в единый DAG (20.09.2026, Решение 42)
`dag_lib.py` (таблица блоков + A*-роутер + Lua-библиотека), `dag_link.py` (одна линия: конвертеры →
цепочка реле с подстанциями → конвертеры; авто-обход при отказе размещения), `dag_links.py L2 L3q ...`
(спецификация и запуск линий), `dag_start.py` (staggered START_OFFSET + одновременный reset счётчиков и
латчей, `--dry` печатает офсеты), `dag_check.py <start_tick>` (сверка латчей с эталоном). Ищем сущности
только по (name, position) — `get_entity_by_unit_number` в этой игре возвращает nil.

## Дополнение 20.09.2026 (вечер)
- `live_revive_batched.py X Y [HX HY]` теперь делает проходы по ВСЕМ ghost'ам (срезы по 400) до прохода без прогресса —
  старая версия застревала при >400 неревайвимых ghost'ов. Неревайвимые из-за перекрытия ghost'ов лечит entity-repair.
- `request_to_generate_chunks` радиус (аргумент live_build_blueprint.py) ≥ половина bbox в чанках по каждой оси
  (±420 тайлов → 14); при нехватке `entities_built=0`. Проверять `is_chunk_generated` по углам.
- Плотные блоки: `dense_matmul_lib.py` (`stage2_dense_fc1_test.py`), `dense_ln_lib.py` (`stage2_dense_ln_test.py`).

## Дополнение 21.09.2026 (П3, Решение 45)
- **Офлайн-гейт перед любой живой постройкой:** `circuit_sim.py` (потиковый симулятор чертежа; самопроверка
  `circuit_sim_selftest.py` на живом микро-тесте). Пример использования — `sim_attn_kv.py`.
- Attention с KV-cache: `dense_attn_lib.py` + эталон `attn_kv_ref.py`; тест `stage2_attn_kv_test.py` →
  `sim_attn_kv.py` (офлайн) → `attn_kv_live.py recon|build|verify|run|clear X Y`. `verify` — только чтение:
  каждая сущность и каждый провод чертежа (включая selector'ы и столбы) против мира + статусы комбинаторов.
  Старый `live_repair_wires.py` знает только arithmetic/decider/constant — для блоков со selector'ами/столбами
  его не использовать без расширения `WIRED`.
- Микро-тест фич 2.0: `stage2_attn_prims_test.py` → `attn_prims_live.py`.

## Дополнение 25.09.2026 (Решения 49-50)
- Вся модель-репетиция: `model_gen.py` (генератор) → `sim_run.py` (офлайн-прогон) → `model_live.py
  recon|prep|build|verify|run|status X Y`. Чертёж >1 МБ заливается в игру частями через `storage`.
- Замер производительности: `ups_probe.py [сек] [--count]` (game.speed=1000, тики/сек = максимум UPS,
  скорость всегда возвращается в 1); нагрузка копиями модели — `ups_load_copies.py build|run|clear K0 K1`;
  векторный стенд — `bench_vector.py build|clear X Y [n] [width]`. **В любом стенде нужен тикающий сигнал
  во входной сети**, иначе комбинаторы не пересчитываются и замер показывает только холостую цену.
- Формулы бюджета — `capacity_table.py` (нуждается в обновлении под векторную упаковку: ~1.9 нс на
  умножение, ~35 нс на холостую сущность, ~0.29 КБ ОЗУ на вес).

## Финальная модель (25.09.2026, Решение 51)
- Эталон `final_ref.py`; блоки `final_blocks.py` / `final_attn_lib.py`; генератор `final_gen.py`;
  офлайн `final_block_test.py`, `sim_final_attn.py`, `sim_final_run.py`; микро-тест сигналов `final_prims_test.py`.
- Живое: `final_live.py recon|prep|build|verify|run|status|chat|clear X Y` (новый мир, постройка на (700,0)).
  build: заливка 49 МБ частями в `storage.fbp` (~1 мин) → build_blueprint (16 с) → revive пачками по 400.
- Чат: `final_live.py chat 700 0` (stdin — реплики пользователя).
