# factorio-transformer

**A real transformer language model running entirely on Factorio 2.0 combinators — no mods, no scripts.**
You type a question into a row of constant combinators, press a button, and the answer appears letter by letter
on a giant lamp board.

[Русская версия](README.ru.md) · **[How to use / Как пользоваться](HOW_TO_USE.md)**

```
you: hi!
bot: hello! i am busy with my factory, but i always have time to talk.
```

## The model

| | |
|---|---|
| architecture | decoder-only pre-LN GPT, character level, greedy decoding |
| size | 6.4 M parameters — 8 layers, 8 heads, d_model 256, FFN 1024, context 256 |
| vocabulary | 36 characters: `a-z`, space, `. , ! ? ' " -`, newline, `:` |
| training | TinyStories, SODA, TinyDialogues, Persona-Chat + generated dialogues about Factorio 2.0 |
| in the game | ~105 000 entities: 53.6 K arithmetic, 18.7 K decider, 18.9 K constant combinators, 8.8 K lamps |
| speed | ~7 s per character at 60 UPS (Ryzen 5 5600) |

It speaks English, knows Factorio (biters, science, trains, Space Age planets), can tell a short story or a joke,
and remembers the conversation while it fits in its 256-character context.

## How it works

1. **Next-character prediction.** The model reads `you: <question>\nbot: `, predicts the most likely next
   character, appends it and repeats until a newline.
2. **Vector weight packing.** Factorio 2.0 arithmetic combinators can compute `each * each` over two networks and
   sum the products — a full dot product in ONE combinator. Each row of a weight matrix is stored as a constant
   combinator; one constant + one arithmetic combinator = one neuron with 256 or 1024 inputs. That is how 6.4 M
   weights fit into ~105 K entities.
3. **2169 signals per wire.** A network carries vectors of 256 (or 1024) values on distinct signals — items,
   fluids, recipes, entities, ... (every signal type of the game passes a circuit network; quality multiplies
   the pool by 5).
4. **Non-linear functions from simple parts.** LayerNorm's square root is Newton's method (4 iterations);
   the softmax exponent is a staircase of 134 decider combinators matching the training-time quantization exactly.
5. **Attention with a KV cache.** Every layer keeps 256 sample-and-hold cells of keys and values; each new
   character attends to all previous ones.
6. **A clock.** One counter steps to the next position every 420 ticks; the signal passes all 8 layers
   (~55 ticks per layer), the predicted character is latched into memory and lit on the board.
7. **Bit-exact.** Everything is integer arithmetic, like the game. `tooling/final_ref.py` computes the same
   integers in Python; the circuit in the game matches it character for character (checked at every position).

The in-game console (`tooling/final_io.py`): 100 query slots (constant combinators, one letter each, a tick ✓ marks
the end), SEND / RESET buttons (constant combinators you switch on and off), a lamp board with a 5×7 pixel font
(query line, progress bar, 150-character reply line). The circuit adds the `you:` / `bot:` markers itself.

## Repository

| path | what |
|---|---|
| `tooling/final_ref.py` | integer reference of the model (the circuit's exact semantics) |
| `tooling/final_blocks.py`, `final_attn_lib.py`, `final_io.py` | circuit components: vector matmul, LayerNorm, attention + KV cache, chat console and lamp board |
| `tooling/final_gen.py` | generator of the whole blueprint |
| `tooling/circuit_builder.py`, `circuit_sim.py`, `sigkeys.py` | blueprint builder, tick-level circuit simulator, signal pool |
| `tooling/final_block_test.py`, `sim_final_attn.py`, `sim_final_io.py`, `sim_final_run.py` | offline gates (simulated blueprint vs reference) |
| `tooling/final_live.py`, `block_live.py`, `rcon_client.py` | building and testing in a running game over RCON |
| `PROJECT.md`, `PROGRESS.md` | full project history (in Russian): every decision, bug and measurement |

Earlier stages are kept too: a keyword classifier (stage 1), a 4-dimensional smoke model, and a 3-layer
rehearsal model (44.5 K entities) that was the first to generate text in the game.

## Try it

Requirements: **Factorio 2.0 with the Space Age expansion** (the circuit uses its item/entity signals), a PC that
keeps 60 UPS with ~105 K combinators (the whole model runs at 60 UPS on a Ryzen 5 5600).

* The ready blueprint is attached to the [latest release](../../releases) (`final_blueprint.txt`, 49 MB).
  Pasting a 49 MB string through the game's import dialog is slow; the reliable way is the RCON builder:
  host the save with RCON enabled, then `python tooling/final_live.py build X Y` (see `tooling/LIVE_OPS_README.md`).
* To regenerate it: get the model weights (`model_ctx256.json`, not included), `python tooling/final_gen.py`.

## License

MIT — see [LICENSE](LICENSE). Authorship mark: [AUTHORSHIP.md](AUTHORSHIP.md).
