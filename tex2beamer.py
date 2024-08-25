import os
import re
import sys
import logging
from openai import OpenAI
import argparse
import subprocess

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

def read_file(file_path: str) -> str:
    with open(file_path, 'r') as file:
        return file.read()
    
def LLMcall(prompt: str, stage: int) -> dict:
    """
    Calls the language model with the provided prompt.
    
    :param prompt: Prompt to send to the language model
    :param stage: Stage 1 or 2. Stage 1 is for the initial prompt, and stage 2 is for the update prompt.
    :return: Response from the language model
    """
    if stage == 1:
        llm_logger.info(f"Sending paper and prompt (based on prompt_initial.txt) to LLM:\n{prompt}") 
        general_logger.info("Sending paper and prompt (based on prompt_initial.txt) to LLM...")
    elif stage == 2:
        llm_logger.info(f"Sending paper and prompt (based on prompt_update.txt) to LLM:\n{prompt}")
        general_logger.info("Sending paper, beamer, and prompt (based on prompt_update.txt) to LLM...")
    elif stage == 3:
        llm_logger.info(f"Sending prompt (based on prompt_revise.txt) to LLM:\n{prompt}")
        general_logger.info("Sending beamer, linter, and prompt (based on prompt_revise.txt) to LLM...")
    else:
        general_logger.error("Invalid stage. Please provide either 1, 2, or 3.")
        sys.exit(1)
    response = client.chat.completions.create(model="gpt-4o",
        messages=[{
                "role": "system",
                "content": "You are a professional assistant specialized in machine learning and deep learning, LaTeX, and Beamer."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
    )
    llm_logger.info(f"Received response from LLM:\n{response}")
    general_logger.info("Received response from LLM.")
    return response

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
    if stage == 1:
        prompt_file = "prompt_initial.txt"
    elif stage == 2:
        prompt_file = "prompt_update.txt"
    elif stage == 3:
        prompt_file = "prompt_revise.txt"
    else:
        general_logger.error("Invalid stage. Please provide either 1, 2, or 3.")
        sys.exit(1)
    
    prompt_template = read_file(prompt_file)
    prompt = prompt_template.replace('PLACEHOLDER_FOR_FIGURE_PATHS', ' '.join(figure_paths))

    if stage == 1:
        full_prompt = (
            f'========The following is the paper ========\n{latex_source}\n ================\n\n'
            f'========The following are the instructions ========\n{prompt}'
        )
    elif stage == 2 or stage == 3:
        full_prompt = (
            f'========The following is the paper ========\n{latex_source}\n ================\n\n'
            f'========The following are the slides ======== \n'
            f'```latex\n{beamer_code}\n```\n ================\n\n'
            f'========The following are the instructions ========\n{prompt}'
        )
        if stage == 3:
            full_prompt += f'\n\n ======== The following is the result of ChkTeX ========\n{linter_log}\n'

    response = LLMcall(full_prompt, stage=stage)
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
    flattened_tex_path = os.path.join(tex_files_directory, "FLATTENED.tex")
    slides_tex_path = os.path.join(tex_files_directory, "slides.tex")

    # Check if FLATTENED.tex exists
    if not os.path.isfile(flattened_tex_path):
        general_logger.error(f"FLATTENED.tex not found in {tex_files_directory}")
        sys.exit(1)

    general_logger.info(f"Using LaTeX file: {flattened_tex_path}")

    # Read the content of FLATTENED.tex
    latex_source = read_file(flattened_tex_path)
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