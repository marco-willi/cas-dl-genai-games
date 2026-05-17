# Notebook Creation Skill

When creating Jupyter notebooks, strictly follow the template at `notebooks/00-xy-example-notebook.ipynb`.

## Naming Convention

Notebooks must be named: `NN-xy-descriptive-text.ipynb`

- `NN` — Incrementing two-digit number (00, 01, 02, …). Check existing notebooks and use the next available number.
- `xy` — Author initials shortcut (two lowercase letters).
- `descriptive-text` — Kebab-case description of the notebook's purpose.

Example: `03-mw-player-detection-analysis.ipynb`

## Required Structure

Every notebook must contain the following cells in this exact order:

### Cell 1 — Setup (code)
```python
%load_ext autoreload

%autoreload 2

from IPython.core.interactiveshell import InteractiveShell

InteractiveShell.ast_node_interactivity = "all"
```

### Cell 2 — Title (markdown)
```markdown
# <Title>

A short description about the purpose of the notebook
```

### Cell 3 — Imports heading (markdown)
```markdown
## Imports
```

### Cell 4 — Imports (code)
```python
import pyrootutils
# define imports here
```

### Cell 5 — Parameters heading (markdown)
```markdown
## Parameters
```

### Cell 6 — Parameters (code)
```python
# define important parameters here
root = pyrootutils.setup_root(
    search_from=__file__,
    indicator="pyproject.toml",
    project_root_env_var=True,
    dotenv=True,
    pythonpath=True,
    cwd=True,
)
```

### Cell 7+ — Sections (markdown + code pairs)
```markdown
## Section

Explain what this section is about.
```
Followed by one or more code cells for that section. Repeat for each logical section.

## Rules

- Never skip or reorder the template cells above.
- Always include the autoreload setup and `pyrootutils.setup_root` boilerplate.
- Add project-specific imports in the Imports code cell, after `import pyrootutils`.
- Each logical section should have a markdown heading cell explaining its purpose, followed by code cells.
