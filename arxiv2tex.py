import requests
import tarfile
import os
import sys
import re
import shutil
import arxiv
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_upload_date(arxiv_id: str) -> datetime:
    try:
        paper = next(arxiv.Client().results(arxiv.Search(id_list=[arxiv_id])))
        return paper.published
    except StopIteration:
        logging.error(f"No paper found with arXiv ID {arxiv_id}.")
        raise

def download_arxiv_source(arxiv_id: str, targz_dir: str = 'targz', source_dir: str = 'source') -> bool:
    url = f'https://arxiv.org/e-print/{arxiv_id}'

    os.makedirs(targz_dir, exist_ok=True)
    os.makedirs(source_dir, exist_ok=True)

    file_name = f'{targz_dir}/{arxiv_id}.tar.gz'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with open(file_name, 'wb') as file:
            file.write(response.content)
    except requests.RequestException as e:
        logging.error(f"Failed to download the file: {e}")
        return False

    try:
        with tarfile.open(file_name) as tar:
            tar.extractall(path=f'{source_dir}/{arxiv_id}')
    except (tarfile.TarError, EOFError) as e:
        logging.error(f"Error extracting the tar file: {e}")
        return False

    logging.info(f"Source files downloaded and extracted to {source_dir}/{arxiv_id}/")
    return True

def find_main_tex(directory: str) -> str | None:
    for file_name in os.listdir(directory):
        if file_name.endswith('.tex'):
            try:
                with open(os.path.join(directory, file_name), 'r', encoding='utf-8') as file:
                    for line in file:
                        if '\\documentclass' in line:
                            return file_name
            except OSError as e:
                logging.warning(f"Could not read file {file_name}: {e}")
    return None

def flatten_tex(directory: str, main_file: str) -> str:
    main_file_path = os.path.join(directory, main_file)
    with open(main_file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    def input_replacer(match):
        file_name = os.path.join(directory, match.group(1))
        if not file_name.endswith('.tex'):
            file_name += '.tex'
        try:
            with open(file_name, 'r', encoding='utf-8') as file:
                return file.read()
        except FileNotFoundError:
            logging.warning(f"{file_name} not found. Skipping.")
            return ''

    return re.sub(r'\\input\{([^}]+)\}', input_replacer, content)

def process_arxiv_source(arxiv_id: str) -> None:
    directory = f'source/{arxiv_id}'
    if not download_arxiv_source(arxiv_id):
        return

    main_file = find_main_tex(directory)
    if not main_file:
        logging.error("Main .tex file not found.")
        return

    tex_files = [f for f in os.listdir(directory) if f.endswith('.tex')]
    flattened_tex_path = os.path.join(directory, 'FLATTENED.tex')

    if len(tex_files) == 1:
        shutil.copyfile(os.path.join(directory, tex_files[0]), flattened_tex_path)
        logging.info(f"Copied {tex_files[0]} to FLATTENED.tex")
    else:
        flattened_content = flatten_tex(directory, main_file)
        with open(flattened_tex_path, 'w', encoding='utf-8') as file:
            file.write(flattened_content)
        logging.info("Saved flattened file in " + flattened_tex_path)

    upload_date = get_upload_date(arxiv_id)
    header = f"% This paper was uploaded to arxiv on {upload_date.strftime('%Y-%m-%d')}\n"
    header += f"% The link to this paper is https://arxiv.org/abs/{arxiv_id}\n\n"

    with open(flattened_tex_path, 'r', encoding='utf-8') as file:
        content = file.read()

    with open(flattened_tex_path, 'w', encoding='utf-8') as file:
        file.write(header + content)
    logging.info("Added header to " + flattened_tex_path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logging.error("Please provide the arXiv ID as an argument.")
        sys.exit(1)

    arxiv_id = sys.argv[1]
    process_arxiv_source(arxiv_id)
