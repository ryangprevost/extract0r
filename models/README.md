# Downloaded model weights

Nothing in this folder is in git. The weights are large, third-party, and reproducible
from a URL — three good reasons to keep them out of a repository. What belongs in git is
this file: where each one came from, what licence it carries, and how to get it back.

`.gitignore` has `models/*` with `!models/README.md`, so a new weight file is ignored by
default and nobody has to remember to add it.

---

## drumsep — `drumsep/49469ca8.th`

Splits a drums stem into kick, snare, cymbals and toms, so a replacement sample lands on
the drum it is named after. Used by `app.services.drums.separate`, off unless
`DRUMSEP_ENABLED=true`.

| | |
|---|---|
| **Source** | https://huggingface.co/vincewin/drumsep (mirror) |
| **Upstream** | https://github.com/inagoy/drumsep |
| **Licence** | MIT, © 2024 Iñaki Goyeneche |
| **Size** | 167 MB (159.6 MiB) |
| **Architecture** | Hybrid Demucs fine-tune — the same family as `htdemucs_6s`, which is why it runs through the demucs CLI unchanged |

```bash
curl -L --fail -o models/drumsep/49469ca8.th https://huggingface.co/vincewin/drumsep/resolve/main/49469ca8.th
```

The filename is not a name anyone chose. `49469ca8` is the signature demucs assigns a set
of weights, and `--repo models/drumsep -n 49469ca8` is how the CLI asks for them, so the
file has to keep that exact name.

**On the mirror.** The Hugging Face copy states its licence as "unknown" while crediting
the MIT original, which is a gap in the mirror's metadata rather than a different licence.
The upstream repository carries an MIT `LICENSE` at its root. If that distinction ever
matters, the Google Drive link in the upstream `drumsepInstall` script is the author's own
copy.

**Why a mirror at all.** The upstream installer pulls from Google Drive with `gdown`,
which is a dependency and a link type that is awkward to script reliably. The Hugging Face
URL is plain HTTPS and versioned.

**Known limits.** The stems are not surgically clean — a loud kick leaves a trace in the
snare file, and `separate.QUIET_STROKE_DB` exists to stop an onset detector reading that
trace as a snare. The model was trained on drum recordings rather than synthesised ones,
unlike LarsNet, which is the main reason it was preferred.

---

## Considered and not used

**LarsNet** — https://github.com/polimi-ispl/larsnet. Five stems rather than four, with
hi-hat separate from cymbals, and five parallel U-Nets that run faster than real time on
CPU. Not used for two reasons: the pretrained weights are **CC BY-NC 4.0**, which is a
licence this project should not take on without a deliberate decision, and it was trained
on StemGMD, which is *synthesised from MIDI* — so a domain gap against real recordings is
likely and would have to be measured before trusting it.
