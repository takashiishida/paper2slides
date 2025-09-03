# core.py
# This file will contain the core logic for paper2slides,
# refactored from the original CLI scripts to be used by the Streamlit app.

import sys
import subprocess
import logging
import yaml
from pathlib import Path
import re
import os
import sys
import logging
from openai import OpenAI
import argparse
import subprocess
import arxiv
import fitz  # PyMuPDF
from arxiv_to_prompt import process_latex_source
from prompts import PromptManager
from dotenv import load_dotenv
import yaml
import time
import requests
from zipfile import ZipFile
import threading
from typing import Optional, Tuple

load_dotenv(override=True)

# Initialize OpenAI client
# client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# MinerU API URL
API_URL = "https://mineru.net/api/v4"


def load_mineru_api_key():
    """Load MinerU API key from environment."""
    api_key = os.getenv("MINERU_API_KEY")
    if not api_key:
        raise RuntimeError("MINERU_API_KEY not found in environment")
    return api_key


def create_task(api_key: str, pdf_url: str) -> str:
    url = f"{API_URL}/extract/task"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "url": pdf_url,
        "extra_formats": ["latex"],
    }
    response = requests.post(url, headers=headers, json=data, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Failed to create task: {result}")
    return result["data"]["task_id"]


def poll_task(
    api_key: str, task_id: str, interval: int = 6, max_wait_seconds: int = 180
) -> dict:
    url = f"{API_URL}/extract/task/{task_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    start_time = time.time()
    attempt = 0
    max_attempts = (
        max_wait_seconds // interval
    )  # Calculate max attempts based on timeout

    while True:
        attempt += 1
        elapsed_time = time.time() - start_time

        # Check timeout before making request
        if elapsed_time > max_wait_seconds:
            logging.error(
                f"MinerU polling timed out after {elapsed_time:.1f}s ({attempt-1} attempts)"
            )
            raise TimeoutError(f"MinerU polling timed out after {max_wait_seconds}s")

        try:
            res = requests.get(url, headers=headers, timeout=30)
            res.raise_for_status()
            result = res.json()
            if result.get("code") != 0:
                raise RuntimeError(f"Failed to get task result: {result}")
            data = result["data"]
            state = data.get("state")

            logging.info(
                f"MinerU task {task_id} poll attempt {attempt}/{max_attempts}: state={state} (elapsed: {elapsed_time:.1f}s)"
            )

            if state == "done":
                logging.info(
                    f"MinerU task completed successfully after {elapsed_time:.1f}s"
                )
                return data
            elif state == "failed":
                error_msg = data.get("err_msg", "Unknown error")
                logging.error(f"MinerU task failed: {error_msg}")
                raise RuntimeError(f"Task failed: {error_msg}")
            elif state not in ["pending", "running"]:
                logging.warning(f"MinerU task in unexpected state: {state}")

        except requests.RequestException as e:
            logging.warning(f"Network error during polling attempt {attempt}: {e}")
            # Continue polling on network errors unless we've timed out

        time.sleep(interval)


def download_and_extract(zip_url: str, output_dir: Path) -> Path:
    response = requests.get(zip_url, stream=True, timeout=60)
    response.raise_for_status()
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "result.zip"
    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    with ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(output_dir)
    return output_dir


def convert_pdf_to_latex(pdf_url: str, output_dir: str) -> Path:
    api_key = load_mineru_api_key()
    task_id = create_task(api_key, pdf_url)
    try:
        result = poll_task(api_key, task_id)
        zip_url = result.get("full_zip_url")
        if not zip_url:
            raise RuntimeError("No result url found")
        return download_and_extract(zip_url, Path(output_dir))
    except TimeoutError as e:
        logging.error(f"MinerU conversion timed out for PDF: {pdf_url}")
        logging.error(
            "This can happen with complex PDFs. Try again or use a different paper."
        )
        raise e
    except Exception as e:
        logging.error(f"MinerU conversion failed for PDF: {pdf_url}")
        raise e


def search_arxiv(query: str, max_results: int = 3) -> list[arxiv.Result]:
    """
    Searches arXiv for a given query and returns the top results.
    """
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    return list(search.results())


def edit_slides(
    beamer_code: str, instruction: str, api_key: str, model_name: str
) -> str | None:
    """
    Edits the Beamer code based on the user's instruction.
    """
    system_message = (
        "You are an expert in LaTeX and Beamer. "
        "Please edit the following Beamer code based on the user's instruction. "
        "Only output the full, updated Beamer code in a single ```latex block."
    )
    user_prompt = f"Instruction: {instruction}\n\nBeamer code:\n{beamer_code}"

    try:
        # Resolve API key and base_url (supports DashScope compatible API)
        resolved_api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
        )
        if not resolved_api_key:
            raise RuntimeError(
                "No API key provided. Set OPENAI_API_KEY or DASHSCOPE_API_KEY."
            )
        client_kwargs = {"api_key": resolved_api_key}
        if resolved_api_key == os.environ.get("DASHSCOPE_API_KEY"):
            client_kwargs["base_url"] = (
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

        client = OpenAI(**client_kwargs)
        # Choose model (auto-adjust for DashScope if an OpenAI model is specified)
        model_to_use = model_name
        if (
            isinstance(client_kwargs.get("base_url"), str)
            and "dashscope.aliyuncs.com" in client_kwargs["base_url"]
            and isinstance(model_name, str)
            and (
                model_name.startswith("gpt-")
                or model_name.startswith("o1")
                or model_name.startswith("o3")
            )
        ):
            model_to_use = os.environ.get("DASHSCOPE_MODEL", "qwen-plus")
        response = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = extract_content_from_response(response)
        if content:
            return sanitize_frametitles(content)
        return None
    except Exception as e:
        logging.error(f"Error editing slides: {e}")
        # Provide guidance for DashScope access issues
        try:
            if "dashscope.aliyuncs.com" in (client_kwargs.get("base_url") or "") and (
                "403" in str(e) or "access_denied" in str(e)
            ):
                logging.error(
                    "DashScope access denied. Ensure your key has access to the model. "
                    "Set DASHSCOPE_MODEL to a model you can use (e.g., qwen-plus)."
                )
        except Exception:
            pass
        return None


# Initialize prompt manager
prompt_manager = PromptManager()


def get_pdflatex_path() -> str:
    """
    Load the pdflatex path from the config file.
    """
    config_path = Path(__file__).parent / "prompts" / "config.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            return config.get("compiler", {}).get("pdflatex_path", "pdflatex")
    except FileNotFoundError:
        logging.warning(
            f"Config file not found at {config_path}. Using default 'pdflatex'."
        )
        return "pdflatex"
    except (yaml.YAMLError, AttributeError) as e:
        logging.warning(f"Error reading config file: {e}. Using default 'pdflatex'.")
        return "pdflatex"


def compile_latex(
    tex_file_path: str, output_directory: str, pdflatex_path: str = "pdflatex"
) -> bool:
    """
    Compiles a LaTeX file to PDF using pdflatex.
    Returns True on success, False on failure.
    """
    try:
        # Pre-sanitize frametitles in slides.tex to avoid '&' errors
        try:
            full_tex_path = Path(output_directory) / tex_file_path
            if full_tex_path.exists():
                original = full_tex_path.read_text(encoding="utf-8", errors="ignore")
                sanitized = sanitize_frametitles(original)
                if sanitized and sanitized != original:
                    full_tex_path.write_text(sanitized, encoding="utf-8")
        except Exception as san_e:
            logging.debug(f"Sanitization skipped due to error: {san_e}")

        command = [pdflatex_path, "-interaction=nonstopmode", tex_file_path]
        # First run
        result1 = subprocess.run(
            command, cwd=output_directory, capture_output=True, text=True
        )
        # Second run to stabilize refs/outlines if needed
        result2 = subprocess.run(
            command, cwd=output_directory, capture_output=True, text=True
        )
        combined_stdout = (result1.stdout or "") + "\n" + (result2.stdout or "")
        combined_stderr = (result1.stderr or "") + "\n" + (result2.stderr or "")

        pdf_path = Path(output_directory) / Path(tex_file_path).with_suffix(".pdf").name
        if result2.returncode != 0:
            logging.error(
                f"Failed to compile the LaTeX file. Check if {pdflatex_path} is installed and the .tex file is correct."
            )
            logging.error(f"pdflatex output:\n{combined_stdout}\n{combined_stderr}")
            # Fallback: consider success if PDF exists
            if pdf_path.exists():
                logging.warning(
                    "pdflatex returned non-zero exit but PDF was produced. Proceeding as success."
                )
                return True
            return False

        if not pdf_path.exists():
            logging.error("pdflatex succeeded but PDF not found.")
            logging.error(f"pdflatex output:\n{combined_stdout}\n{combined_stderr}")
            return False

        logging.info(f"Successfully compiled {tex_file_path} using {pdflatex_path}.")
        return True
    except FileNotFoundError:
        logging.error(
            f"Failed to find the pdflatex compiler at '{pdflatex_path}'. Please check your config.yaml or system PATH."
        )
        return False


def read_file(file_path: str) -> str:
    """Read a file and return its contents as a string."""
    # Try different encodings in order of preference
    encodings = ["utf-8", "latin-1", "cp1252", "iso-8859-1"]

    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as file:
                return file.read()
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logging.error(
                f"Error reading file {file_path} with encoding {encoding}: {e}"
            )
            continue

    # If all encodings fail, try reading as binary and decode with errors='replace'
    try:
        with open(file_path, "rb") as file:
            content = file.read()
            return content.decode("utf-8", errors="replace")
    except Exception as e:
        logging.error(f"Failed to read file {file_path} with any encoding: {e}")
        raise


def find_image_files(directory: str) -> list[str]:
    """
    Searches for image files (.pdf, .png, .jpeg, .jpg) in the specified directory and
    returns their paths relative to the specified directory.
    """
    image_extensions = [".pdf", ".png", ".jpeg", ".jpg"]
    image_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if any(file.endswith(ext) for ext in image_extensions):
                relative_path = os.path.relpath(os.path.join(root, file), directory)
                image_files.append(relative_path)
    return image_files


def extract_content_from_response(
    response: dict, language: str = "latex"
) -> str | None:
    """
    :param response: Response from the language model
    :param language: Language to extract (default is 'latex')
    :return: Extracted content
    """
    pattern = re.compile(rf"```{language}\s*(.*?)```", re.DOTALL)
    match = pattern.search(response.choices[0].message.content)
    content = match.group(1).strip() if match else None
    return content


def _process_latex_source_worker(
    arxiv_id: str, cache_dir: str, result_container: list
) -> None:
    try:
        latex = process_latex_source(
            arxiv_id,
            keep_comments=False,
            remove_appendix_section=True,
            cache_dir=cache_dir,
        )
        result_container.append((True, latex))
    except Exception as e:
        result_container.append((False, e))


def get_latex_from_arxiv_with_timeout(
    arxiv_id: str, cache_dir: str, timeout_seconds: int = 120
) -> Optional[str]:
    """
    Attempt to retrieve LaTeX source from arXiv using arxiv-to-prompt, but
    give up after timeout_seconds to avoid hanging the UI.
    """
    result_container: list[Tuple[bool, object]] = []
    thread = threading.Thread(
        target=_process_latex_source_worker,
        args=(arxiv_id, cache_dir, result_container),
    )
    thread.daemon = True
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        logging.warning("Timed out retrieving LaTeX from arXiv (arxiv-to-prompt).")
        return None
    if not result_container:
        return None
    success, payload = result_container[0]
    if success:
        return payload if isinstance(payload, str) and payload.strip() else None
    else:
        logging.warning(f"arxiv-to-prompt error: {payload}")
        return None


def extract_definitions_and_usepackage_lines(latex_source: str) -> list[str]:
    """
    Extracts definitions and usepackage lines from LaTeX source
    """
    commands = ["\\def", "\\DeclareMathOperator", "\\DeclarePairedDelimiter"]
    packages_to_comment_out = [
        "amsthm",
        "color",
        "hyperref",
        "xcolor",
        "ragged2e",
        "times",
        "graphicx",
        "enumitem",
    ]
    extracted_lines = []

    lines = latex_source.split("\n")
    for line in lines:
        if any(line.strip().startswith(cmd) for cmd in commands):
            extracted_lines.append(line)
        if line.strip().startswith("\\usepackage"):
            # Skip packages that may conflict with Beamer
            if any(pkg in line for pkg in packages_to_comment_out):
                extracted_lines.append("% " + line)
            else:
                extracted_lines.append(line)
    return extracted_lines


def build_additional_tex(defs_and_pkgs: list[str]) -> str:
    """
    Build ADDITIONAL.tex contents from extracted lines.
    """
    header = [
        "% Auto-generated by paper2slides",
        "% This file aggregates definitions and package imports from the paper.",
    ]
    return "\n".join(header + defs_and_pkgs)


def save_additional_tex(contents: str, dest_dir: str) -> None:
    path = Path(dest_dir) / "ADDITIONAL.tex"
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(contents)


def add_additional_tex(content: str) -> str:
    """
    Ensure that \input{ADDITIONAL.tex} is present. If missing, add near the top after documentclass.
    """
    if not content:
        return content
    if "\\input{ADDITIONAL.tex}" in content:
        return content
    # Insert after documentclass line
    pattern = re.compile(
        r"(\\documentclass\[[^\]]*\]\{beamer\}|\\documentclass\{beamer\})"
    )

    def _inserter(m: re.Match) -> str:
        return m.group(1) + "\n\\input{ADDITIONAL.tex}"

    new_content, count = pattern.subn(_inserter, content, count=1)
    if count == 0:
        logging.warning("\\input{ADDITIONAL.tex} is missing. Added manually.")
        return "\\input{ADDITIONAL.tex}\n" + content
    return new_content


def sanitize_frametitles(beamer_code: str) -> str:
    """
    Escapes unescaped ampersands inside \frametitle and its arguments.
    Also sanitizes titles provided via \begin{frame}{...} with optional [options].
    Handles <...>, [...], and {...} arguments with optional whitespace.
    """
    if not beamer_code:
        return ""

    # 1) Sanitize titles in \begin{frame}[opts]{Title}
    def repl_frame(match):
        begin_frame = match.group(1)
        options = match.group(2) or ""
        title = match.group(3)
        sanitized_options = re.sub(r"(?<!\\)&", r"\\&", options)
        sanitized_title = re.sub(r"(?<!\\)&", r"\\&", title)
        return f"{begin_frame}{sanitized_options}{{{sanitized_title}}}"

    pattern_frame = re.compile(r"(\\begin\{frame\})\s*(\[[^\]]*\])?\s*\{([^}]*)\}")
    beamer_code = pattern_frame.sub(repl_frame, beamer_code)

    # 2) Sanitize explicit \frametitle commands
    def repl(match):
        # Groups: 1=\frametitle, 2=<...>, 3=[...], 4={...} content
        command = match.group(1)
        overlay = match.group(2) or ""
        short_title = match.group(3) or ""
        main_title = match.group(4)

        sanitized_overlay = re.sub(r"(?<!\\)&", r"\\&", overlay)
        sanitized_short_title = (
            re.sub(r"(?<!\\)&", r"\\&", short_title) if short_title else ""
        )
        sanitized_main_title = re.sub(r"(?<!\\)&", r"\\&", main_title)

        return f"{command}{sanitized_overlay}{sanitized_short_title}{{{sanitized_main_title}}}"

    pattern = re.compile(
        r"(\\frametitle)\s*(<[^>]*>)?\s*(\[[^\]]*\])?\s*\{(.*?)\}", re.DOTALL
    )

    return pattern.sub(repl, beamer_code)


def process_stage(
    stage: int,
    latex_source: str,
    beamer_code: str,
    linter_log: str,
    figure_paths: list[str],
    slides_tex_path: str,
    api_key: str,
    model_name: str,
):

    system_message, user_prompt = prompt_manager.build_prompt(
        stage=stage,
        latex_source=latex_source,
        beamer_code=beamer_code,
        linter_log=linter_log,
        figure_paths=figure_paths,
    )

    try:
        # Resolve API key and base_url (supports DashScope compatible API)
        resolved_api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
        )
        if not resolved_api_key:
            raise RuntimeError(
                "No API key provided. Set OPENAI_API_KEY or DASHSCOPE_API_KEY."
            )
        client_kwargs = {"api_key": resolved_api_key}
        if resolved_api_key == os.environ.get("DASHSCOPE_API_KEY"):
            client_kwargs["base_url"] = (
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

        client = OpenAI(**client_kwargs)
        # Choose model (auto-adjust for DashScope if an OpenAI model is specified)
        model_to_use = model_name
        if (
            isinstance(client_kwargs.get("base_url"), str)
            and "dashscope.aliyuncs.com" in client_kwargs["base_url"]
            and isinstance(model_name, str)
            and (
                model_name.startswith("gpt-")
                or model_name.startswith("o1")
                or model_name.startswith("o3")
            )
        ):
            model_to_use = os.environ.get("DASHSCOPE_MODEL", "qwen-plus")
        response = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt},
            ],
        )

        logging.info("Received response from LLM.")

    except Exception as e:
        logging.error(f"Error generating prompt for stage {stage}: {e}")
        # Provide guidance for DashScope access issues
        try:
            if "dashscope.aliyuncs.com" in (client_kwargs.get("base_url") or "") and (
                "403" in str(e) or "access_denied" in str(e)
            ):
                logging.error(
                    "DashScope access denied. Ensure your key has access to the model. "
                    "Set DASHSCOPE_MODEL to a model you can use (e.g., qwen-plus)."
                )
        except Exception:
            pass
        return False

    new_beamer_code = extract_content_from_response(response)

    new_beamer_code = sanitize_frametitles(new_beamer_code)

    if not new_beamer_code:
        logging.error("No beamer code found in the response.")
        return False

    with open(slides_tex_path, "w") as file:
        file.write(new_beamer_code)
    logging.info(f"Beamer code saved to {slides_tex_path}")
    return True


def generate_slides(
    arxiv_id: str,
    use_linter: bool,
    use_pdfcrop: bool,
    api_key: str | None = None,
    model_name: str = "gpt-4.1-2025-04-14",
) -> bool:
    # Define paths
    cache_dir = f"cache/{arxiv_id}"
    tex_files_directory = f"source/{arxiv_id}/"
    slides_tex_path = f"{tex_files_directory}slides.tex"

    # Create directories if not exist
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(tex_files_directory, exist_ok=True)

    # Fetch LaTeX source
    logging.info("Fetching LaTeX source from arXiv...")
    latex_source = get_latex_from_arxiv_with_timeout(arxiv_id, cache_dir)
    if latex_source is None:
        logging.info(
            "Falling back to PDF-to-LaTeX extraction via MinerU (may take longer)..."
        )
        try:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            extracted_dir = convert_pdf_to_latex(pdf_url, tex_files_directory)
            # Read the .tex file (heuristic: choose the largest .tex file)
            tex_files = list(Path(extracted_dir).glob("**/*.tex"))
            if not tex_files:
                logging.error("No .tex files found in the extracted MinerU result.")
                return False
            main_tex_file = max(tex_files, key=lambda p: p.stat().st_size)
            latex_source = read_file(str(main_tex_file))
        except Exception as e:
            logging.error(f"PDF-to-LaTeX fallback failed: {e}")
            return False

    # Extract definitions and packages to build ADDITIONAL.tex
    logging.info("Extracting definitions and packages...")
    defs_pkgs = extract_definitions_and_usepackage_lines(latex_source)
    add_tex_contents = build_additional_tex(defs_pkgs)
    save_additional_tex(add_tex_contents, tex_files_directory)

    # Add \input{ADDITIONAL.tex} if missing
    latex_source = add_additional_tex(latex_source)

    # Find images under source dir to restrict allowed figures
    figure_paths = find_image_files(tex_files_directory)

    # Stage 1: initial generation
    logging.info("Stage 1: generating slides...")
    if not process_stage(
        1,
        latex_source,
        "",
        "",
        figure_paths,
        slides_tex_path,
        api_key or "",
        model_name,
    ):
        return False

    logging.info("Stage 2: refining slides with update prompt...")
    beamer_code = read_file(slides_tex_path)  # read generated beamer code from stage 1
    if not process_stage(
        2,
        latex_source,
        beamer_code,
        "",
        figure_paths,
        slides_tex_path,
        api_key or "",
        model_name,
    ):
        return False

    # Process stage 3 (if linter is used)
    if not use_linter:
        logging.info("Skipping linter stage. Generation complete.")
        return True

    logging.info("Stage 3: running chktex and revising slides...")
    subprocess.run(
        [
            "chktex",
            "-o",
            "linter.log",
            "slides.tex",
        ],
        cwd=tex_files_directory,
    )
    linter_log = read_file(f"{tex_files_directory}linter.log")

    beamer_code = read_file(slides_tex_path)  # read updated beamer code from stage 2
    if not process_stage(
        3,
        latex_source,
        beamer_code,
        linter_log,
        figure_paths,
        slides_tex_path,
        api_key or "",
        model_name,
    ):
        return False

    logging.info("All stages completed successfully.")
    return True
