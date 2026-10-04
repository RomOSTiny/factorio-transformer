# Factorio Transformer — как использовать

В репозитории три части: сохранение мира `AI_In_FACTORIO.zip`, эта инструкция и папка `model/`
с готовой Python-моделью и её весами. Это посимвольная языковая модель на 6,4 млн параметров,
контекст 256 символов. Она отвечает по-английски; качество ответов ограничено размером модели.

## Запустить Python-модель

Игра, Space Age, GPU и PyTorch для этого не нужны. Нужны **Python 3.10 или новее** и **NumPy**.
Скачайте репозиторий через **Code → Download ZIP**, распакуйте его и откройте терминал в этой папке.

```sh
python -m pip install numpy
python model/model.py
```

На Windows вместо `python` можно использовать `py -3`, на Linux/macOS — `python3`.
Введите, например, `hi!`, `what are biters?` или `tell me a joke.`
`/reset` очищает память разговора, `/quit` завершает программу.
При заполнении контекста следующий вопрос начинает новый разговор.

Один вопрос без интерактивного режима:

```sh
python model/model.py --prompt "hi!"
```

Модель использует те же целочисленные операции, округления и жадный выбор символов,
что и схема в игре. Веса уже находятся в `model/weights.npz`; программа не скачивает модели
и не обращается к внешним сервисам. Формат обучения — `you: <вопрос>\nbot: <ответ>\n`.
Память и скорость в Python зависят от компьютера.

---

# Как поговорить с ИИ в Factorio

Нужны Factorio 2.0 и дополнение Space Age.

1. **Скачайте сейв** `AI_In_FACTORIO.zip` из этого репозитория или [релиза](https://github.com/RomOSTiny/factorio-transformer/releases/tag/v1.0). Поместите его в папку сохранений Factorio и загрузите как обычное сохранение. В Windows эта папка — `%APPDATA%\Factorio\saves`.
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

1. **Download** `AI_In_FACTORIO.zip` from this repository or the [release](https://github.com/RomOSTiny/factorio-transformer/releases/tag/v1.0), put it in your Factorio saves folder, and load it as a normal save. On Windows the folder is `%APPDATA%\Factorio\saves`.
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

## Run the Python model

Requires Python 3.10+ and NumPy; no game, GPU, PyTorch or external service is required.
Download and extract the repository, open a terminal in its folder, then run:

```sh
python -m pip install numpy
python model/model.py
```

Ask questions in English. `/reset` clears conversation history; `/quit` exits.
For one question: `python model/model.py --prompt "hi!"`.
The 256-character context starts a new conversation when the next question no longer fits.
The included weights and integer inference reproduce the model's circuit arithmetic.
This is a small experimental character model, so responses can be inaccurate or repetitive.


## License / Лицензия

```text
MIT License

Copyright (c) 2026 RomOSTiny

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
