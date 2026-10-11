# Training data / Обучающие данные

Prepared data retained from training the 6,393,344-parameter Factorio language model.
This is a snapshot of the corpus currently available locally, including the final
Factorio/persona/name examples. Earlier training stages changed the generated corpus;
this download is not a reconstruction of every historical stage or its sampling order.

## Download

[Download the complete prepared corpus (ZIP)](https://github.com/RomOSTiny/factorio-transformer/releases/download/training-data-2026-10-11/training_data_2026-10-11.zip).
Extract the ZIP beside this folder: all files have one top-level `training_data/` directory.
Large corpus files are release assets rather than Git blobs.

## Sources and licenses

| Corpus | Original source | License |
|---|---|---|
| tinystories | [TinyStories, Ronen Eldan and Yuanzhi Li](https://huggingface.co/datasets/roneneldan/TinyStories), GPT-4 V2 train/validation | CDLA-Sharing-1.0 |
| storychat | TinyStories paragraphs converted to story-request conversations | CDLA-Sharing-1.0 |
| tinydialogues | [TinyDialogues, Steven Y. Feng, Noah D. Goodman and Michael C. Frank](https://huggingface.co/datasets/styfeng/TinyDialogues) | MIT |
| soda | [SODA, Hyunwoo Kim et al., Allen Institute for AI](https://huggingface.co/datasets/allenai/soda) | CC-BY-4.0 |
| personachat | [Synthetic-Persona-Chat, Pegah Jandaghi et al.](https://huggingface.co/datasets/google/Synthetic-Persona-Chat) | CC-BY-4.0 |
| factorio | Project-generated conversations from `knowledge/*.txt` | MIT |

Third-party data retain the licenses above; the project's MIT license does not
replace them. Full license texts and original dataset cards are in `licenses/`.
Changes: lowercase/character normalization, filtering, dialogue role conversion,
turn-length limits and tokenization. `storychat` adds generated questions to story excerpts.
See `prepare_data.py` for transformations. Project code and knowledge are covered by
the project's [MIT license](../HOW_TO_USE.md).

## Contents and format

- `knowledge/`: readable Factorio facts, persona, name and story templates.
- `prepare_data.py`, `generate_factorio.py`, `tokenizer.py`: preparation tools.
- `manifest.json`: token alphabet, corpus sizes, document counts and SHA-256 checksums.
- `corpus/` (in the ZIP): prepared training and validation streams for all six sources.
- `read_corpus.py`: decode streams to readable text or show a few documents.

`<source>_<train|val>.bin` is a stream of uint8 character-token IDs (not model weights).
The alphabet order is recorded in `manifest.json`. Blank lines separate documents.
`*_docs.npy` contains int64 document-start offsets; `*_turns.npy` contains user-turn offsets.
No pickle is required.

```sh
python -m pip install numpy
python training_data/read_corpus.py training_data/corpus/factorio_train.bin --documents 3
python training_data/read_corpus.py training_data/corpus/factorio_train.bin --output factorio_train.txt
```

To regenerate data from upstream raw files, install `training_data/requirements.txt`,
place the original files in `training_data/raw/` using the paths in `prepare_data.py`,
then run `python training_data/prepare_data.py`.
`python training_data/generate_factorio.py 800000` regenerates the final generated source
from the included templates. Use the archived streams for the retained snapshot.

## По-русски

Полный подготовленный корпус доступен одним ZIP по ссылке выше; всё находится в папке
`training_data`. Здесь есть исходные факты и шаблоны проекта, описание источников,
лицензии и программа для преобразования обучающих токенов в обычный текст.
Это сохранённая версия корпуса, а не точное восстановление всех ранних этапов обучения.
