# Как провести замер ёмкости (Phase B) — чек-лист

Файлы уже готовы: `stress_test_500.txt`, `stress_test_2000.txt`, `stress_test_5000.txt` (в этой же папке).

1. F4 → включить `show-fps`, `show-time-usage`, `hide-mod-guis`
2. Замерить пустой мир — записать значение строки **"Circuit networks"** (мс/тик)
3. Импортировать `stress_test_500.txt` (библиотека чертежей → Import string), достроить призраков:
   ```
   /c for _, e in pairs(game.player.surface.find_entities_filtered{type="entity-ghost"}) do e.revive() end
   ```
   Подождать пару секунд, записать "Circuit networks"
4. То же самое с `stress_test_2000.txt` (лучше в новом чистом мире, чтобы не путать старые схемы с новыми)
5. То же самое с `stress_test_5000.txt`
6. Прислать все 4 числа (пусто / 500 / 2000 / 5000) — дальше расчёт делает Claude
