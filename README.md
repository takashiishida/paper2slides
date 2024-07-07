# paper2slides

Transform any arXiv papers into slides using Large Language Models (LLMs)! This tool is useful for quickly grasping the main ideas of research papers.

The process starts with downloading the source files of an arXiv paper. The main LaTeX file is identified and flattened, merging all input files into one. The LLMs are then employed to generate Beamer code from this LaTeX source.
Since the LLM may generate beamer slides with some issues in the first run, we ask the LLM again to self-inspect which usually increases the quality and removes some bugs.
Finally, the Beamer code is compiled into a PDF presentation using pdflatex.

The main components of this project are `arxiv2tex.py` (downloads and processes arXiv source files), `tex2beamer.py` (converts LaTeX files into Beamer presentations), and `beamer2pdf.py` (creates a PDF file with pdflatex).
`all.zsh` is a script to automate the process by running these three Python scripts sequentially and opening the resulting PDF. Usually only takes about 90 seconds when I am using `gpt-4o`.

Some examples of the generated slides: [Transformer paper](demo/transformer.pdf), [DPO paper](demo/DPO.pdf), and [Mirage of emergent abilities paper](demo/mirage.pdf).

## Requirements

- Python 3.10 or higher
- `requests` library
- `arxiv` library
- `openai` library
- OpenAI API key
- A working installation of `pdflatex`

## Installation

1. Clone this repository:
    ```sh
    git clone <repository-url>
    cd <repository-directory>
    ```

2. Install the required Python packages:
    ```sh
    pip install requests arxiv openai
    ```

3. Ensure `pdflatex` is installed and available in your system's PATH. Optionally check if you can compile the sample `test.tex` by `pdflatex test.tex`. Check if `test.pdf` is genereated correctly.

4. Set up your OpenAI API key:
    ```sh
    export OPENAI_API_KEY='your-api-key'
    ```

## Usage

### Using `all.sh` Script

This script automates the process of downloading an arXiv paper, processing it, and converting it to a Beamer presentation.

```sh
bash all.sh <arxiv_id>
```

Replace `<arxiv_id>` with the desired arXiv paper ID.
The ID can be identified from the URL: the ID for `https://arxiv.org/abs/xxxx.xxxx` is `xxxx.xxxx`.

### Individual Scripts

You can also run the Python scripts individually for more control.

1. **Download and Process arXiv Source Files**

    ```sh
    python arxiv2tex.py <arxiv_id>
    ```

    This script downloads the source files of the specified arXiv paper, extracts them, and processes the main LaTeX file. Results will be saved in `source/<arxiv_id>/FLATTENED.tex`.

2. **Convert LaTeX to Beamer**

    ```sh
    python tex2beamer.py <arxiv_id>
    ```

    This script reads the processed LaTeX files and prepares Beamer slides. This is where we are using the OpenAI API. We call twice, first to generate the beamer code, and then to self-inspect the beamer code.
    The prompts sent to the LLM and the response from the LLM will be saved in `tex2beamer.log`.

3. **Convert Beamer to PDF**
    ```sh
    python beamer2pdf.py <arxiv_id>
    ```
    
    This script compiles the beamer file into a PDF presentation.

### Prompts
The prompts are saved in `prompt_initial.txt` and `prompt_update.txt` but feel free to adjust them to your needs.
- `prompt_intial.txt` contains a placeholder called `% PLACEHOLDER_FOR_NEWCOMMANDS`. This will be replaced with the new commands and other definitions used in the paper. We aim to use all new commands in our beamer code, rather than relying on the LLM to choose the necessary ones, as this proved to be unreliable in my attempts.
- `prompt-update.txt` contains a placeholder called `PLACEHOLDER_FOR_FIGURE_PATHS`. This will be replaced with the figure paths used in the paper. We want to make sure the paths are correctly used in the beamer code. The LLM often made mistakes, so we explicitly include this in the prompt.

## Notes
- Notice how everything stays in the LaTeX world, meaning we do not need any vision capabilities. The LLM can vaguely understand the figures from the captions of the papers, and we can also use the figures in our slides.
- In my experience, this tends to work better for papers with less equations. It may fail when the paper is very long (will exceed the token limit), when the LLM fails to pick up the necessary packages, and when some advanced features are used in the original paper, such as using `\iftoggle{}` for figure paths. There may be many other edge cases.
- The script will send information to the OpenAI API. Be mindful of the content being shared!
- I believe this tool is great for a quick summary, but note that this is still experimental. For a more accurate or for a deeper understanding, you should definitely read the full paper.
- The project has been tested on MacOS and Linux.
- If you have suggestions for improvements, encounter any issues, or want to add new features, please feel free to let me know!
