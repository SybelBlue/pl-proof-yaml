# PrairieLearn Proof YAML Course

This PrairieLearn course repository contains examples and local development files for the `pl-proof-yaml` element. You can also view and edit the live course at [prairielearn.com](https://prairielearn.com).

## Install in a PrairieLearn course

From the root of your PrairieLearn course, clone the `release` branch into
`elements/pl-proof-yaml`:

```sh
git clone --branch release --single-branch \
  https://github.com/SybelBlue/pl-proof-yaml.git \
  elements/pl-proof-yaml
```

To update an existing installation to the latest release, run:

```sh
git -C elements/pl-proof-yaml pull --ff-only origin release
```

## Developers

### Prerequisites

Install the following tools:

- [Git](https://git-scm.com/)
- [Python 3.13 or newer](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Node.js and npm](https://nodejs.org/) for the Prettier checks

Clone the repository, enter its directory, and install the Python environment:

```sh
git clone <repository-url>
cd pl-proof-yaml
uv sync
```

Replace `<repository-url>` with this repository's Git URL. `uv sync` creates a local `.venv` and installs the project dependencies recorded in `uv.lock`.

### Vendored PyYAML

The parser's `yaml` package comes from PyYAML's `lib/yaml` directory. Its source
commit and destination are declared in `pyproject.toml`, and
`plvendor-lock.yaml` records the exact revision. The patch in
`.vendor-patches/pyyaml.patch` keeps the optional C extension import relative to
this nested package and preserves the existing file contents.

Check that the committed copy is reproducible with:

```sh
uv run --locked pl-vendor verify
```

To update PyYAML, change the full release commit in `pyproject.toml`, then run
`uv run pl-vendor update pyyaml`. Review the source diff, adjust the patch if
needed, and run `uv run --locked pl-vendor verify` and `make test-unit` before
committing the manifest, lockfile, patch, and generated files together.

### Get started in VS Code

Open the repository from its root so that VS Code loads the checked-in workspace settings:

```sh
code .
```

Install the [YAML extension by Red Hat](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml). You can install it from the Extensions view by searching for `redhat.vscode-yaml`, or from a terminal:

```sh
code --install-extension redhat.vscode-yaml
```

The repository's [`.vscode/settings.json`](.vscode/settings.json) configures VS Code to treat the custom proof files as YAML and assigns each kind of file to its JSON schema:

```jsonc
{
  "yaml.schemas": {
    "./elements/pl-proof-yaml/pl_proof_yaml/schemas/proof.schema.json": [
      "/**/*.proof",
      "/**/*.proof.yaml",
    ],
    "./elements/pl-proof-yaml/pl_proof_yaml/schemas/proofs.schema.json": [
      "/**/*.proofs",
      "/**/*.proofs.yaml",
    ],
    "./elements/pl-proof-yaml/pl_proof_yaml/schemas/manifest.schema.json": [
      "/**/*.manifest",
      "/**/*.manifest.yaml",
    ],
  },
  "files.associations": {
    "*.proof": "yaml",
    "*.proofs": "yaml",
    "*.manifest": "yaml",
  },
  "yaml.format.enable": false,
}
```

No manual settings changes are needed when you open this repository as a folder. The file associations activate YAML language support for `.proof`, `.proofs`, and `.manifest` files; `yaml.schemas` then provides validation, completion, hover documentation, and other schema-aware editing. YAML formatting is disabled in the Red Hat extension because this repository uses Prettier as its YAML formatter.

If you are setting up a separate workspace, run **Preferences: Open Workspace Settings (JSON)** from the Command Palette and copy the settings above into that workspace's `.vscode/settings.json`. Adjust the relative schema paths if that workspace has a different directory layout.

## Working with PrairieLearn

Learn how to create questions and assessments with PrairieLearn's [Get Started tutorial](https://prairielearn.readthedocs.io/en/latest/getStarted/).

## Getting Help

- Ask for real-time assistance in PrairieLearn's [Slack `#pl-help` channel](https://prairielearn.com/slack).
- Search the [PrairieLearn FAQ](https://prairielearn.readthedocs.io/en/latest/faq/) and [GitHub Discussions](https://github.com/PrairieLearn/PrairieLearn/discussions/categories/q-a).
- Attend virtual office hours, which are announced at the start of the semester in [PrairieLearn Slack](https://prairielearn.com/slack).

## Element guide

`pl-proof-yaml` turns a proof written in YAML into an interactive proof-reconstruction question. Students arrange proof lines in a valid order and, when a line contains a blank, choose the missing expression from a drop-down menu. Authors describe the mathematics and its dependency structure; the element builds and grades the PrairieLearn inputs.

### Quick start

Create `serverFilesCourse/proofs/odd-square.proof`:

```yaml
problem: If $n$ is odd, then $n^2$ is odd.
defaults:
  depends: previous
lines:
  - step: Let $n$ be odd, so BLANK for some integer $k$.
    correct: $n = 2k + 1$
    incorrect:
      - $n = 2k$
      - $n = k + 1$
  - step: Squaring and expanding gives BLANK.
    correct: $n^2 = 4k^2 + 4k + 1$
    incorrect: $n^2 = 4k^2 + 1$
  - step: Therefore $n^2 = 2(2k^2 + 2k) + 1$, so $n^2$ is odd.
```

Then place the element in `question.html`:

```html
<pl-proof-yaml
  answers-name="proof"
  proof-file="proofs/odd-square.proof"
  directory="serverFilesCourse"
  grading-method="dag"
  source-blocks-order="random-sections"
  partial-credit="lcs"
  feedback="first-wrong"
></pl-proof-yaml>
```

`answers-name` must be unique within the question. The default `directory` is `serverFilesCourse`, so that attribute may be omitted in this example.

### The proof model

A proof has a `problem`, an optional `hint`, and `lines`. Each line may be a plain string or an object with a `step` and additional behavior.

```yaml
problem: A theorem statement.
hint: An optional author-supplied hint.
lines:
  - A line with no blank or special behavior.
  - step: A configurable proof line.
```

Lines are correct proof blocks, not necessarily a single fixed sequence. With `grading-method="dag"`, `depends` describes a directed acyclic graph: a line can be placed after all its prerequisites while independent lines may appear in any order. This is useful for proofs with parallel arguments, cases, or steps whose order is mathematically irrelevant.

List-based lines receive one-based numeric IDs. A mapping can provide explicit numeric IDs, although this is legacy syntax:

```yaml
lines:
  10: Assume $n$ is odd.
  20:
    step: Write $n = 2k + 1$ for an integer $k$.
    depends: 10
  30:
    step: Hence $n^2$ is odd.
    depends: 20
```

List-based authoring is preferred for new `.proof` files. In either form, a dependency must refer to an earlier line, and dependencies may not form a cycle.

### Dependencies and definitions

`depends` accepts a numeric line ID, a list of dependencies, `previous`, `"previous: N"`, `"previous: all"`, a previously defined mathematical identifier, or the expanded mapping form. For example:

```yaml
defaults:
  depends: previous
lines:
  - step: Introduce $x$ and $y$.
    defines: $x, y$
  - An intermediate step.
  - step: Uses both immediately preceding steps.
    depends:
      previous: 2
  - step: Uses the lines that introduced $x$ and $y$, plus line 3.
    depends:
      names: $x, y$
      lines: 3
```

Use `anyOf` when any one of several dependency groups is sufficient. Items within
one alternative are all required, while the alternatives are joined with
PrairieLearn's `|` dependency operator:

```yaml
lines:
  - First route.
  - Second route, part one.
  - step: Second route, part two.
    depends: 2
  - step: Finish after either route.
    depends:
      anyOf:
        - 1
        - [2, 3]
```

Use `defaults` for properties shared by most lines; a value on an individual line overrides that default. `dependents: all-below` makes every later line in the same scope depend on the marked line, which is convenient for a standing assumption. Prefer expressing prerequisites with `depends` when practical because it keeps the relationship local to the line that needs them.

The parser also understands mathematical identifiers such as `$n$`. `defines` records the identifiers introduced by a line, allowing later `depends` values to refer to those identifiers:

```yaml
- step: Let $n$ be an odd integer.
  defines: $n$
- step: Since $n$ is odd, $n = 2k + 1$ for an integer $k$.
  depends: $n$
  defines: $k$
```

Identifiers found for the first time are inferred as definitions, but explicit `defines` is helpful when the intended scope would otherwise be unclear.

### Fill-in blanks

The shorthand form uses the literal marker `BLANK`, one correct answer, and one or more incorrect choices:

```yaml
- step: Proof by BLANK.
  correct: contradiction
  incorrect:
    - induction
    - contrapositive
```

Use named blanks when one line needs multiple drop-downs. Every key under `blanks` must occur as a marker in `step`:

```yaml
- step: Since FACT, we may conclude RESULT.
  blanks:
    FACT:
      correct: $n = 2k$
      incorrect: $n = 2k + 1$
    RESULT:
      correct: $n^2$ is even
      incorrect:
        - $n^2$ is odd
        - $n$ is prime
```

MathJax may be used in line text and choices. Quote YAML values when punctuation could be interpreted as YAML syntax.

### Distractors

Distractors are plausible lines that do not belong in the completed proof. Top-level distractors are global; distractors nested under a line are associated with that line. Both may be plain text or contain blanks using the same syntax as correct lines.

```yaml
problem: If $n$ is even, then $n^2$ is even.
distractors:
  - Therefore $n$ is odd.
lines:
  - step: Write $n = 2k$ for some integer $k$.
    distractors:
      - Write $n = 2k + 1$ for some integer $k$.
  - Therefore $n^2 = 4k^2 = 2(2k^2)$ is even.
```

Use distractors to target recognizable misconceptions rather than merely adding noise. Associated distractors are especially useful for presenting a tempting alternative beside the correct step.

### Subgoals

A subgoal groups a nested sequence under a proof-line heading. Nested lines inherit a dependency on the subgoal header, so they remain inside the relevant branch of the argument.

```yaml
lines:
  - subgoal: First show that $A \subseteq B$.
    lines:
      - Let $x \in A$.
      - step: Show that $x \in B$.
        depends: previous
  - subgoal: Now show that $B \subseteq A$.
    lines:
      - Let $x \in B$.
      - step: Show that $x \in A$.
        depends: previous
```

Subgoals suit case splits, biconditionals, set equality by double inclusion, and proofs with intermediate lemmas.

### Loading proofs

The element can load a single proof, a collection, a manifest, or a directory:

| Source                          | Purpose                                                            |
| ------------------------------- | ------------------------------------------------------------------ |
| `.proof` or `.proof.yaml`       | One proof object.                                                  |
| `.proofs` or `.proofs.yaml`     | A list or mapping of proof objects. Select one with `proof-index`. |
| `.manifest` or `.manifest.yaml` | A `proofs` list containing paths to individual proof files.        |
| Directory via `proof-dir`       | Loads its proof files, or its single manifest when one is present. |

Paths are resolved relative to `directory`, which may be `serverFilesCourse`, `clientFilesCourse`, `clientFilesQuestion`, or `question`. Use exactly one of `proof-file` and `proof-dir`. `proof-index` is zero-based and defaults to `0`.

```html
<!-- Select the fifth proof in a collection. -->
<pl-proof-yaml
  answers-name="proof"
  proof-file="contradictions.proofs"
  proof-index="4"
></pl-proof-yaml>
```

An assessment preference can choose the path dynamically:

```html
<pl-proof-yaml answers-name="proof" proof-file="{{preferences.proof_file}}"></pl-proof-yaml>
```

### Element attributes

The most commonly used attributes are:

| Attribute                | Meaning                                                                                        | Default             |
| ------------------------ | ---------------------------------------------------------------------------------------------- | ------------------- |
| `answers-name`           | PrairieLearn answer namespace; required and unique per question.                               | none                |
| `proof-file`             | Path to a proof, collection, or manifest.                                                      | none                |
| `proof-dir`              | Path to a directory of proofs.                                                                 | none                |
| `directory`              | PrairieLearn directory against which the path is resolved.                                     | `serverFilesCourse` |
| `proof-index`            | Zero-based proof selected from the loaded results.                                             | `0`                 |
| `grading-method`         | Ordering strategy passed to `pl-order-blocks`; use `dag` for dependency-aware grading.         | `dag`               |
| `source-blocks-order`    | Initial ordering of the available lines.                                                       | `random-sections`   |
| `partial-credit`         | Partial-credit strategy passed to `pl-order-blocks`.                                           | element default     |
| `feedback`               | Feedback strategy passed to `pl-order-blocks`.                                                 | element default     |
| `source-header`          | Heading above the available proof lines.                                                       | element default     |
| `solution-header`        | Heading above the student's constructed proof.                                                 | element default     |
| `solution-placement`     | Placement of the constructed proof, such as `right`.                                           | element default     |
| `hide-problem-statement` | If `true`, do not render the YAML `problem`; useful when `question.html` states it separately. | `false`             |

The element also forwards `weight`, `inline`, `display-blocks`, and `allow-blank` to `pl-order-blocks`. See the PrairieLearn `pl-order-blocks` documentation for the accepted values and grading details of forwarded attributes.

### Authoring recommendations

- Start with `defaults: {depends: previous}` for a linear proof, then replace dependencies where steps may commute or branches merge.
- Keep each block focused on one logical move. Very long blocks make ordering less meaningful; extremely short blocks can turn the activity into guesswork.
- Include incorrect blank choices that represent specific algebraic or logical errors.
- Use `.proofs` collections or manifests to reuse a common question template across many theorems.
- Keep the theorem statement in `problem` unless the surrounding `question.html` must provide richer markup; in that case set `hide-problem-statement="true"`.
- Use the checked-in JSON schemas while editing to catch missing fields, invalid attributes, and malformed dependency expressions early.
