# Как поговорить с ИИ в Factorio

Нужны Factorio 2.0 и дополнение Space Age.

1. **Загрузите сейв** `AI_In_FACTORIO.zip` из [релиза](https://github.com/RomOSTiny/factorio-transformer/releases/tag/v1.0) как обычное сохранение.
2. **Перейдите к пульту**: консоль `~`, команда `/c game.player.teleport({262, -431})`. Над пультом инструкции на табличках, их видно по **Alt**.
3. **Наберите вопрос по-английски** в ряд константных комбинаторов, слева направо, по одной букве в каждый:
   - буквы — сигналы `A`–`Z` из вкладки «Виртуальные сигналы»;
   - пробел — сигнал «Точка» (кружок);
   - знаки `. , ! ? ' " -` — одноимённые сигналы.
4. **В комбинатор сразу после последней буквы поставьте галочку ✓.** Всё, что дальше, не читается, стирать старые буквы не нужно.
5. **Нажмите «ОТПРАВИТЬ»** (левый комбинатор над началом ряда): включите его, потом выключите.
6. **Смотрите на табло ниже**: `/c game.player.teleport({300, -362})`. Сначала заполняется прогресс-бар (модель читает вопрос), потом ответ появляется по одной букве, примерно по 7 секунд.
7. **Следующий вопрос** задаётся тем же способом после того, как ответ закончится. Модель помнит разговор, пока он помещается в 256 символов.
8. **«СБРОС»** (кнопка рядом): включить и выключить, и начнётся новый разговор.

Модель отвечает по-английски и знает Factorio, может рассказать историю или пошутить. Пока она отвечает, кнопка «ОТПРАВИТЬ» не срабатывает.

---

# How to talk to the AI in Factorio

Requires Factorio 2.0 with the Space Age expansion.

1. **Load the save** `AI_In_FACTORIO.zip` from the [release](https://github.com/RomOSTiny/factorio-transformer/releases/tag/v1.0) as a normal save.
2. **Go to the console**: open the console `~` and run `/c game.player.teleport({262, -431})`. Signs above the console explain everything (press **Alt**).
3. **Type your question in English** into the row of constant combinators, left to right, one letter per combinator:
   - letters are the `A`–`Z` signals on the "Virtual signals" tab;
   - space is the "Dot" signal (the circle);
   - `. , ! ? ' " -` are the signals of the same name.
4. **Put a check mark ✓ into the combinator right after the last letter.** Nothing after it is read, so old letters don't need to be erased.
5. **Press SEND** (the left combinator above the start of the row): switch it on, then off.
6. **Watch the lamp board below**: `/c game.player.teleport({300, -362})`. The progress bar fills first (the model is reading the question), then the answer appears letter by letter, about 7 seconds each.
7. **Ask the next question** the same way once the answer is finished. The model remembers the conversation while it fits in 256 characters.
8. **RESET** (the button next to SEND): switch it on and off to start a new conversation.

The model answers in English and knows Factorio; it can also tell a story or a joke. SEND does nothing while it is answering.
