# paper2slides

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) ![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4.1-412991.svg) ![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg) ![arXiv](https://img.shields.io/badge/arXiv-papers-b31b1b.svg)


Transform any arXiv papers into slides using LLMs! This tool is useful for quickly grasping the main ideas of research papers. Some examples of generated slides are in the [Demo](demo/) directory.

## Installation

Python 3.10 or higher is required.

To install:

1. Clone this repository:
    ```sh
    git clone https://github.com/takashiishida/paper2slides.git
    cd paper2slides
    ```

2. Install the required Python packages:
    ```sh
    pip install -r requirements.txt
    ```

3. Ensure `pdflatex` is installed and available in your system's PATH. Optionally check if you can compile the sample `test.tex` by `pdflatex test.tex`. Check if `test.pdf` is generated correctly. Optionally check `chktex` and `pdfcrop` are working.

4. Set up your OpenAI API key:
    ```sh
    export OPENAI_API_KEY='your-api-key'
    ```

## Quick Start

Once installed, generate slides from any arXiv paper:

```sh
python paper2slides.py all 2505.18102
```

This will download the paper, generate slides, compile to PDF, and open the presentation automatically.

## Usage

### CLI

The `paper2slides.py` script provides a CLI interface with subcommands:

```sh
# Full pipeline (most common usage)
python paper2slides.py all <arxiv_id>

# Generate slides (beamer) only
python paper2slides.py generate <arxiv_id>

# Generate slides (beamer) with linting and PDF cropping
python paper2slides.py generate <arxiv_id> --use_linter --use_pdfcrop

# Compile slides (beamer) to PDF
python paper2slides.py compile <arxiv_id>

# Full pipeline without opening PDF
python paper2slides.py all <arxiv_id> --no-open
```

Replace `<arxiv_id>` with the desired arXiv paper ID.
The ID can be identified from the URL: the ID for `https://arxiv.org/abs/xxxx.xxxx` is `xxxx.xxxx`.

The underlying `tex2beamer.py` and `beamer2pdf.py` scripts handle the core functionality:
- `tex2beamer.py` downloads and processes the arXiv paper using `arxiv-to-prompt`, then generates Beamer slides via OpenAI API
- `beamer2pdf.py` compiles the LaTeX slides to PDF using pdflatex

The prompts sent to the LLM and responses are logged to `tex2beamer.log`.
Linter output (when `--use_linter` is used) is saved to `source/<arxiv_id>/linter.log`.

### Prompts

The prompts are now managed through a YAML-based system in `prompts/config.yaml`. This file contains:

- **Template variables**: Common settings like `num_slides`, `max_items`, `figure_width`, etc.
- **Stage management**: Separate prompts for `initial`, `update`, and `revise` stages
- **Default values**: Configurable defaults for audience, formatting, and dimensions
- **Variable substitution**: Dynamic replacement of `{variable}` placeholders

You can customize the prompts by editing `prompts/config.yaml`. The system automatically handles figure path insertion and other dynamic content. The `PromptManager` class in `prompts/manager.py` handles template rendering and validation.

## How does it work?

The process begins by downloading the source files of an arXiv paper. The main LaTeX file is identified and flattened, merging all input files into a single document (`FLATTENED.tex`) with [arxiv-to-prompt](https://github.com/takashiishida/arxiv-to-prompt). We preprocess this merged file by removing comments and the appendix. This preprocessed file, along with instructions for creating good slides, forms the basis of our prompt.

One key idea is to use Beamer for slide creation, allowing us to stay entirely within the LaTeX ecosystem. This approach essentially turns the task into a summarization exercise: converting a long LaTeX paper into concise Beamer LaTeX. The LLM can infer the content of figures from their captions and include them in the slides, eliminating the need for vision capabilities.

To aid the LLM, we create a file called `ADDITIONAL.tex`, which contains all necessary packages, \newcommand definitions, and other LaTeX settings used in the paper. Including this file with `\input{ADDITIONAL.tex}` in the prompt shortens it and makes generating slides more reliable, particularly for theoretical papers with many custom commands.

The LLM generates Beamer code from the LaTeX source, but since the first run may have issues, we ask the LLM to self-inspect and refine the output. Optionally, a third step involves using a linter to check the generated code, with the results fed back to the LLM for further corrections (this linter step was inspired by [The AI Scientist](https://www.arxiv.org/abs/2408.06292)). Finally, the Beamer code is compiled into a PDF presentation using pdflatex.

The unified `paper2slides.py` script automates the entire process, typically completing in less than a few minutes with GPT-4.1 for a single paper.

> [!WARNING]
> The script will download files from the internet (arXiv), send information to the OpenAI API, and compile locally. Please be cautious about the content being shared and the potential risks.
