import os
import re
import sys
import logging
from openai import OpenAI
import argparse
import subprocess
from arxiv_to_prompt import process_latex_source
from prompts import PromptManager

# Set up general logging
general_logger = logging.getLogger('general')
general_logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
general_logger.addHandler(console_handler)
# Set up LLM logging (only to file)
llm_logger = logging.getLogger('llm')
llm_logger.setLevel(logging.INFO)
llm_file_handler = logging.FileHandler('tex2beamer.log')
llm_file_handler.setLevel(logging.INFO)
llm_file_handler.setFormatter(formatter)
llm_logger.addHandler(llm_file_handler)

# Initialize OpenAI client
client = OpenAI(api_key=os.environ['OPENAI_API_KEY'])

# Initialize prompt manager
prompt_manager = PromptManager()

def read_file(file_path: str) -> str:
    """Read a file and return its contents as a string."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def find_image_files(directory: str) -> list[str]:
    """
    Searches for image files (.pdf, .png, .jpeg, .jpg) in the specified directory and
    returns their paths relative to the specified directory.
    """
    image_extensions = ['.pdf', '.png', '.jpeg', '.jpg']
    image_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if any(file.endswith(ext) for ext in image_extensions):
                relative_path = os.path.relpath(os.path.join(root, file), directory)
                image_files.append(relative_path)
    return image_files


def extract_content_from_response(response: dict, language: str = 'latex') -> str | None:
    """
    :param response: Response from the language model
    :param language: Language to extract (default is 'latex')
    :return: Extracted content
    """
    pattern = re.compile(rf'```{language}\s*(.*?)```', re.DOTALL)
    match = pattern.search(response.choices[0].message.content)
    content = match.group(1).strip() if match else None
    return content

def extract_definitions_and_usepackage_lines(latex_source: str) -> list[str]:
    """
    Extracts definitions and usepackage lines from LaTeX source
    """
    commands = ['\\def', '\\DeclareMathOperator', '\\DeclarePairedDelimiter']
    packages_to_comment_out = ['amsthm', 'color', 'hyperref', 'xcolor', 'ragged2e', 'times', 'graphicx', 'enumitem']
    extracted_lines = []

    lines = latex_source.split('\n')
    inside_command = False
    accumulated_command = []

    for line in lines:
        stripped_line = line.strip()

        if inside_command:
            accumulated_command.append(stripped_line)
            if stripped_line.endswith('}'):
                extracted_lines.append(' '.join(accumulated_command))
                inside_command = False
                accumulated_command = []
            continue

        if any(stripped_line.startswith(cmd) for cmd in commands) and not stripped_line.startswith('%'):
            accumulated_command.append(stripped_line)
            if stripped_line.endswith('}'):
                extracted_lines.append(' '.join(accumulated_command))
                accumulated_command = []
            else:
                inside_command = True
            continue

        if stripped_line.startswith('\\usepackage') and not stripped_line.startswith('%'):
            main_part, sep, comment = line.partition('%')
            main_part = main_part.strip()
            comment = sep + comment if sep else ''

            match = re.match(r'\\usepackage(\[.*?\])?\{(.*?)\}', main_part)
            if match:
                package_name = match.group(2)
                wrapped_line = f"\\IfFileExists{{{package_name}.sty}}{{{main_part}}}{{}}{comment}"
                
                if package_name in packages_to_comment_out:
                    wrapped_line = f"% {wrapped_line}"
                
                extracted_lines.append(wrapped_line)

    return extracted_lines

def extract_newcommands(latex_source: str) -> list[str]:
    """
    Extracts all newcommand definitions from a LaTeX document, including multi-line definitions with nested and escaped braces
    """
    # pattern to match both \newcommand{\cmdname} and \newcommand\cmdname
    pattern = re.compile(r'\\newcommand\s*(\\\w+|{\s*\\\w+\s*})\s*(\[[0-9]+\])?\s*{', re.DOTALL)
    
    matches = []
    start_pos = 0

    while True:
        # Search for the next \newcommand
        match = pattern.search(latex_source, start_pos)
        if not match:
            break
        
        # Extract the starting position of the matched \newcommand
        start = match.start()
        
        # Find the closing brace for this \newcommand
        brace_count = 0
        end_pos = match.end()
        while end_pos < len(latex_source):
            char = latex_source[end_pos]
            
            # Skip over escaped braces
            if char == '\\' and end_pos + 1 < len(latex_source) and latex_source[end_pos + 1] in '{}':
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
        matches.append(latex_source[start:end_pos])
        
        # Move the start position to search for the next \newcommand
        start_pos = end_pos
    
    return matches

def save_additional_commands(directory: str, latex_source: str) -> None:
    """
    Extracts LaTeX definitions and saves them to ADDITIONAL.tex
    """
    additional_tex_path = os.path.join(directory, 'ADDITIONAL.tex')

    lines_1 = extract_definitions_and_usepackage_lines(latex_source)
    lines_2 = extract_newcommands(latex_source)
    lines = lines_1 + lines_2

    if not lines:
        general_logger.info("No additional commands or packages found in LaTeX source.")
        # Create empty ADDITIONAL.tex file
        with open(additional_tex_path, 'w', encoding='utf-8') as file:
            file.write('% Additional LaTeX packages and commands\n')
        return

    with open(additional_tex_path, 'w', encoding='utf-8') as file:
        file.write('\n'.join(lines))

    general_logger.info(f"Extracted and saved additional commands and packages to {additional_tex_path}")

def add_additional_tex(content: str) -> str:
    """
    Check if \input{ADDITIONAL.tex} exists (LLM may ignore the instruction to include this)
    """
    if content and not re.search(r'\\input\{ADDITIONAL\.tex\}', content):
        # Add \input{ADDITIONAL.tex} after \documentclass line
        content = re.sub(r'\\documentclass.*', r'\g<0>\n\\input{ADDITIONAL.tex}', content, count=1)
        general_logger.info("\\input{ADDITIONAL.tex} is missing. Added manually.")
    return content

def process_stage(stage: int, latex_source: str, beamer_code: str, linter_log: str, figure_paths: list[str], slides_tex_path: str):
    """
    Sends the prompt to the language model, extracts the Beamer code from the response, and saves it to the specified path.
    """
    # Map stage numbers to stage names
    stage_names = {1: 'initial', 2: 'update', 3: 'revise'}
    
    if stage not in stage_names:
        general_logger.error("Invalid stage. Please provide either 1, 2, or 3.")
        sys.exit(1)
    
    stage_name = stage_names[stage]
    
    # Prepare variables for prompt rendering
    prompt_vars = {
        'latex_source': latex_source,
        'figure_paths': ' '.join(figure_paths)
    }
    
    # Add stage-specific variables
    if stage in [2, 3]:  # update and revise stages need beamer_code
        prompt_vars['beamer_code'] = beamer_code
    
    if stage == 3:  # revise stage needs linter_log
        prompt_vars['linter_log'] = linter_log
    
    try:
        # Get the rendered prompt and system message
        system_message = prompt_manager.get_system_message(stage_name)
        user_prompt = prompt_manager.get_prompt(stage_name, **prompt_vars)
        
        general_logger.info(f"Sending paper and prompt (based on {stage_name} stage) to LLM...")
        
        # Call the LLM with the new prompt format
        response = client.chat.completions.create(
            model="gpt-4.1-2025-04-14",
            messages=[{
                "role": "system",
                "content": system_message
            }, {
                "role": "user",
                "content": user_prompt
            }]
        )
        
        llm_logger.info(f"Sent prompt for stage '{stage_name}' to LLM:\n{user_prompt}")
        llm_logger.info(f"Received response from LLM:\n{response}")
        general_logger.info("Received response from LLM.")
        
    except Exception as e:
        general_logger.error(f"Error generating prompt for stage {stage}: {e}")
        sys.exit(1)

    new_beamer_code = extract_content_from_response(response)
    new_beamer_code = add_additional_tex(new_beamer_code)
    
    if not new_beamer_code:
        general_logger.error("No beamer code found in the response.")
        sys.exit(1)

    with open(slides_tex_path, 'w') as file:
        file.write(new_beamer_code)
    general_logger.info(f'Beamer code saved to {slides_tex_path}')


def main(args):
    # Define paths
    tex_files_directory = f"source/{args.arxiv_id}/"
    slides_tex_path = os.path.join(tex_files_directory, "slides.tex")

    # Create directory if it doesn't exist
    os.makedirs(tex_files_directory, exist_ok=True)

    # Get LaTeX source using arxiv-to-prompt with custom cache directory
    general_logger.info(f"Getting LaTeX source for {args.arxiv_id} using arxiv-to-prompt")
    try:
        latex_source = process_latex_source(
            args.arxiv_id, 
            keep_comments=False, 
            remove_appendix_section=True,
            cache_dir=tex_files_directory
        )
    except Exception as e:
        general_logger.error(f"Failed to get LaTeX source from arxiv-to-prompt: {e}")
        sys.exit(1)

    # Extract and save additional commands to ADDITIONAL.tex
    save_additional_commands(tex_files_directory, latex_source)

    # Find image files in the downloaded directory
    figure_paths = find_image_files(tex_files_directory)

    if args.use_pdfcrop:
        for figure_path in figure_paths:
            if figure_path.endswith('.pdf'):
                subprocess.run(["pdfcrop", os.path.join(tex_files_directory, figure_path), os.path.join(tex_files_directory, figure_path)])


    # Process stage 1
    process_stage(1, latex_source, '', '', figure_paths, slides_tex_path)

    # Process stage 2
    beamer_code = read_file(slides_tex_path) # read generated beamer code from stage 1
    process_stage(2, latex_source, beamer_code, '', figure_paths, slides_tex_path)

    # Process stage 3 (if linter is used)
    if not args.use_linter:
        return None

    subprocess.run(["chktex", "-o", f"{tex_files_directory}linter.log", slides_tex_path])
    linter_log = read_file(f"{tex_files_directory}linter.log")
    
    beamer_code = read_file(slides_tex_path) # read updated beamer code from stage 2
    process_stage(3, latex_source, beamer_code, linter_log, figure_paths, slides_tex_path)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Generate Beamer slides from LaTeX papers.")
    parser.add_argument('--arxiv_id', type=str, help='The arXiv ID of the paper to process')
    parser.add_argument('--use_linter', action='store_true', help='Whether to use the linter')
    parser.add_argument('--use_pdfcrop', action='store_true', help='Whether to use pdfcrop')
    args = parser.parse_args()
    main(args)