import argparse
import requests
import tarfile
import os
import re
import arxiv
import logging
from datetime import datetime
from arxiv_latex_cleaner.arxiv_latex_cleaner import _remove_comments_inline

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
    """
    We assume that the main file contains the \documentclass command.
    If there are multiple files with \documentclass, the one with the most lines is chosen.
    """
    main_tex_file = None
    max_line_count = 0

    for file_name in os.listdir(directory):
        if file_name.endswith('.tex') and file_name != 'FLATTENED.tex':
            try:
                with open(os.path.join(directory, file_name), 'r', encoding='utf-8') as file:
                    lines = file.readlines()
                    if any('\\documentclass' in line for line in lines):
                        line_count = len(lines)
                        if line_count > max_line_count:
                            main_tex_file = file_name
                            max_line_count = line_count
            except OSError as e:
                logging.warning(f"Could not read file {file_name}: {e}")

    return main_tex_file

def flatten_tex(directory: str, main_file: str) -> str:
    main_file_path = os.path.join(directory, main_file)
    
    with open(main_file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    def input_replacer(match):
        # Normalize the file path by resolving relative paths
        file_name = os.path.normpath(os.path.join(directory, match.group(1).strip()))
        if not file_name.endswith('.tex'):
            file_name += '.tex'
        try:
            # Recursively replace \input or \include commands in the included content
            return flatten_tex(directory, os.path.relpath(file_name, directory))
        except FileNotFoundError:
            logging.warning(f"{file_name} not found. Skipping.")
            return ''
    
    # Combine \input{file}, \input file, \include{file}, and \include file patterns
    input_patterns = [
        r'\\input\{([^}]+)\}',       # \input{file}
        r'\\input\s+([^\s{}]+)',      # \input file
        r'\\include\{([^}]+)\}',      # \include{file}
        r'\\include\s+([^\s{}]+)'     # \include file
    ]

    # Process each pattern
    for pattern in input_patterns:
        content = re.sub(pattern, input_replacer, content)

    logging.info(f"Flattened the .tex files with {main_file}")
    return content

def remove_comments_from_lines(lines: str) -> str:
    wo_comment_list = [_remove_comments_inline(line) for line in lines.split('\n')]
    return ''.join(wo_comment_list)

def extract_newcommands(file_path: str) -> list[str]:
    """
    Extracts all newcommand definitions from a LaTeX document, including multi-line definitions
    with nested and escaped braces, and handles both braced and unbraced command names.
    Returns a list of strings, each containing a \newcommand definition.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        latex_text = file.read()
    
    # pattern to match both \newcommand{\cmdname} and \newcommand\cmdname
    pattern = re.compile(r'\\newcommand\s*(\\\w+|{\s*\\\w+\s*})\s*(\[[0-9]+\])?\s*{', re.DOTALL)
    
    matches = []
    start_pos = 0

    while True:
        # Search for the next \newcommand
        match = pattern.search(latex_text, start_pos)
        if not match:
            break
        
        # Extract the starting position of the matched \newcommand
        start = match.start()
        
        # Find the closing brace for this \newcommand
        brace_count = 0
        end_pos = match.end()
        while end_pos < len(latex_text):
            char = latex_text[end_pos]
            
            # Skip over escaped braces
            if char == '\\' and end_pos + 1 < len(latex_text) and latex_text[end_pos + 1] in '{}':
                end_pos += 2
                continue
            
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == -1:  # Matched the closing brace for \newcommand
                    end_pos += 1
                    break
            end_pos += 1
        
        # Append the full \newcommand definition to the list of matches
        matches.append(latex_text[start:end_pos])
        
        # Move the start position to search for the next \newcommand
        start_pos = end_pos
    
    return matches


def extract_definitions_and_usepackage_lines(file_path: str) -> list[str]:
    '''
    Extracts LaTeX \\def, \\DeclareMathOperator, \\DeclarePairedDelimiter, and \\usepackage lines from a file.
    Wraps \\usepackage lines with \\IfFileExists to ensure they are ignored if the package is not loadable.
    Comments out \\usepackage lines that rely on local style files (i.e., .sty files that exist in the same directory as the file).

    :param file_path: Path to the LaTeX file
    :return: List of command and package lines
    '''
    commands = ['\\def', '\\DeclareMathOperator', '\\DeclarePairedDelimiter']
    packages_to_comment_out = ['amsthm', 'color', 'hyperref', 'xcolor', 'ragged2e', 'times', 'graphicx', 'enumitem']
    extracted_lines = []

    # Get the directory of the LaTeX file
    file_dir = os.path.dirname(file_path)

    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    inside_command = False
    accumulated_command = []

    for line in lines:
        stripped_line = line.strip()

        # Check if we are in the middle of accumulating a multi-line command
        if inside_command:
            accumulated_command.append(stripped_line)
            # Check if the line ends the command (assuming it ends with "}")
            if stripped_line.endswith('}'):
                extracted_lines.append(' '.join(accumulated_command))
                inside_command = False
                accumulated_command = []
            continue

        # Start accumulating if a command begins
        if any(stripped_line.startswith(cmd) for cmd in commands) and not stripped_line.startswith('%'):
            accumulated_command.append(stripped_line)
            # If the command is complete in this line, add it directly
            if stripped_line.endswith('}'):
                extracted_lines.append(' '.join(accumulated_command))
                accumulated_command = []
            else:
                inside_command = True
            continue

        # Process \usepackage commands as before
        if stripped_line.startswith('\\usepackage') and not stripped_line.startswith('%'):
            main_part, sep, comment = line.partition('%')
            main_part = main_part.strip()
            comment = sep + comment if sep else ''

            match = re.match(r'\\usepackage(\[.*?\])?\{(.*?)\}', main_part)
            if match:
                package_name = match.group(2)
                wrapped_line = f"\\IfFileExists{{{package_name}.sty}}{{{main_part}}}{{}}{comment}"
                
                sty_file_path = os.path.join(file_dir, f"{package_name}.sty")
                if package_name in packages_to_comment_out or os.path.exists(sty_file_path):
                    wrapped_line = '% ' + wrapped_line

                extracted_lines.append(wrapped_line)
            else:
                extracted_lines.append(main_part + comment)

    return extracted_lines



def save_additional_commands(directory: str) -> None:
    additional_tex_path = os.path.join(directory, 'ADDITIONAL.tex')
    flattened_tex_path = os.path.join(directory, 'FLATTENED.tex')

    if not os.path.exists(flattened_tex_path):
        logging.error(f"{flattened_tex_path} does not exist.")
        return

    lines_1 = extract_definitions_and_usepackage_lines(flattened_tex_path)
    lines_2 = extract_newcommands(flattened_tex_path)
    lines = lines_1 + lines_2

    if not lines:
        logging.info("No additional commands or packages found in FLATTENED.tex.")
        return

    with open(additional_tex_path, 'w', encoding='utf-8') as file:
        file.write('\n'.join(lines))

    logging.info(f"Extracted and saved additional commands and packages to {additional_tex_path}")


def remove_appendix(tex_content: str) -> str:
    # Find the start of the appendix
    appendix_start = tex_content.find('\\appendix')
    
    if appendix_start != -1:
        # Look for \end{document} only after \appendix
        # some papers have \start{document} and \end{document} several times.
        appendix_end = tex_content.find('\\end{document}', appendix_start)
        
        if appendix_end != -1:
            # Remove the appendix content if both \appendix and \end{document} exist and \end{document} is after \appendix
            tex_content = tex_content[:appendix_start] + tex_content[appendix_end:]
            logging.info("Removed appendix from tex content.")
        else:
            logging.info("No \\end{document} found after \\appendix.")
    else:
        logging.info("No appendix found in tex content.")

    return tex_content


def process_arxiv_source(arxiv_id: str) -> None:
    directory = f'source/{arxiv_id}'
    if not download_arxiv_source(arxiv_id):
        return

    main_file = find_main_tex(directory)
    if not main_file:
        logging.error("Main .tex file not found.")
        return

    tex_files = [os.path.join(root, f) for root, _, files in os.walk(directory) for f in files if f.endswith('.tex') and f != 'FLATTENED.tex']
    logging.info(f"Found {len(tex_files)} .tex files (excluding FLATTENED.tex, if already created).")
    flattened_tex_path = os.path.join(directory, 'FLATTENED.tex')

    if len(tex_files) == 1:
        with open(tex_files[0], 'r', encoding='utf-8') as file:
            flattened_content = file.read()
    else:
        flattened_content = flatten_tex(directory, main_file)
    
    flattened_content = remove_comments_from_lines(flattened_content)
    flattened_content = remove_appendix(flattened_content)

    with open(flattened_tex_path, 'w', encoding='utf-8') as file:
        file.write(flattened_content)
    logging.info(f"Copied {tex_files[0]} to FLATTENED.tex") if len(tex_files) == 1 else logging.info("Saved flattened file in " + flattened_tex_path)

    upload_date = get_upload_date(arxiv_id)
    header = f"% This paper was uploaded to arxiv on {upload_date.strftime('%Y-%m-%d')}\n"
    header += f"% The link to this paper is https://arxiv.org/abs/{arxiv_id}\n\n"

    with open(flattened_tex_path, 'r', encoding='utf-8') as file:
        content = file.read()

    with open(flattened_tex_path, 'w', encoding='utf-8') as file:
        file.write(header + content)
    logging.info("Added header to " + flattened_tex_path)

    save_additional_commands(directory)

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Process arXiv LaTeX sources.")
    parser.add_argument("arxiv_id", type=str, help="The arXiv ID of the paper to process")
    parser.add_argument("--targz_dir", type=str, default="targz", help="Directory to save downloaded tar.gz files")
    parser.add_argument("--source_dir", type=str, default="source", help="Directory to save extracted source files")
    args = parser.parse_args()

    process_arxiv_source(args.arxiv_id)
