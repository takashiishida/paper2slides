import os
import re
import sys
import logging
from openai import OpenAI

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

def extract_newcommand_lines(file_path: str) -> list[str]:
    """
    Extracts LaTeX \newcommand, \def, \DeclareMathOperator, and \DeclarePairedDelimiter lines from a file.
    
    :param file_path: Path to the LaTeX file
    :return: List of command lines
    """
    commands = ['\\newcommand', '\\def', '\\DeclareMathOperator', '\\DeclarePairedDelimiter']
    with open(file_path, 'r') as file:
        lines = file.readlines()
    return [
        line.strip() for line in lines
        if any(cmd in line for cmd in commands) and not line.strip().startswith('%')
    ]

def extract_figure_paths(latex_code: str) -> list[str]:
    """
    Extracts the paths of figures from LaTeX code.
    
    :param latex_code: LaTeX code as a string
    :return: List of figure paths
    """
    pattern = re.compile(r'\\includegraphics(?:\[.*?\])?\{(.*?)\}')
    return pattern.findall(latex_code)

def read_file(file_path: str) -> str:
    """
    Reads the content of a file.
    
    :param file_path: Path to the file
    :return: Content of the file
    """
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
        llm_logger.info(f"Sending paper and prompt (based on prompt_initial.txt) to LLM:\n{prompt}")  # Log the prompt to the LLM log file
        general_logger.info("Sending paper and prompt (based on prompt_initial.txt) to LLM...")
    elif stage == 2:
        llm_logger.info(f"Sending paper and prompt (based on prompt_update.txt) to LLM:\n{prompt}")  # Log the prompt to the LLM log file
        general_logger.info("Sending paper, beamer, and prompt (based on prompt_update.txt) to LLM...")
    else:
        general_logger.error("Invalid stage. Please provide either 1 or 2.")
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
    llm_logger.info(f"Received response from LLM:\n{response}")  # Log the response to the LLM log file
    general_logger.info("Received response from LLM.")
    return response

def extract_content_from_response(response: dict, language: str = 'latex') -> str | None:
    """
    Extracts content from the language model's response.
    
    :param response: Response from the language model
    :param language: Language to extract (default is 'latex')
    :return: Extracted content
    """
    pattern = re.compile(rf'```{language}\s*(.*?)```', re.DOTALL)
    match = pattern.search(response.choices[0].message.content)
    return match.group(1).strip() if match else None

def main(arxiv_id):
    # Define paths
    tex_files_directory = f"source/{arxiv_id}/"
    flattened_tex_path = os.path.join(tex_files_directory, "FLATTENED.tex")
    beamer_prompt_file = "prompt_initial.txt"
    beamer_update_prompt_file = "prompt_update.txt"
    slides_tex_path = os.path.join(tex_files_directory, "slides.tex")

    # Check if FLATTENED.tex exists
    if not os.path.isfile(flattened_tex_path):
        general_logger.error(f"FLATTENED.tex not found in {tex_files_directory}")
        sys.exit(1)

    general_logger.info(f"Using LaTeX file: {flattened_tex_path}")

    # Read the content of FLATTENED.tex
    latex_source = read_file(flattened_tex_path)
    figure_paths = extract_figure_paths(latex_source)
    newcommand_lines = extract_newcommand_lines(flattened_tex_path)
    newcommand_lines_str = '\n'.join(newcommand_lines)

    # Prepare beamer prompt
    beamer_prompt = read_file(beamer_prompt_file)
    beamer_prompt = beamer_prompt.replace('% PLACEHOLDER_FOR_NEWCOMMANDS', newcommand_lines_str)
    full_prompt = latex_source + '\n' + beamer_prompt

    # Get initial beamer code
    response = LLMcall(full_prompt, stage=1)
    beamer_code = extract_content_from_response(response)
    if beamer_code:
        general_logger.info("Beamer code extracted.")
    else:
        general_logger.error("No beamer code found in the response.")
        sys.exit(1)

    # Prepare updated prompt
    beamer_update_prompt = read_file(beamer_update_prompt_file)
    beamer_update_prompt = beamer_update_prompt.replace('PLACEHOLDER_FOR_FIGURE_PATHS', ' '.join(figure_paths))
    updated_full_prompt = f'========The following is the paper ========\n{latex_source}\n ======== The following are the slides ======== \n```latex\n{beamer_code}\n```\n ======== The following are the instructions ========\n{beamer_update_prompt}'

    # Get updated beamer code
    response = LLMcall(updated_full_prompt, stage=2)
    updated_beamer_code = extract_content_from_response(response)
    if not updated_beamer_code:
        general_logger.error("No updated beamer code found in the response.")
        sys.exit(1)

    # Write the updated beamer code to a .tex file
    with open(slides_tex_path, 'w') as file:
        file.write(updated_beamer_code)
    general_logger.info(f'Content saved to {slides_tex_path}')

if __name__ == "__main__":
    if len(sys.argv) > 1:
        arxiv_id = sys.argv[1]
        main(arxiv_id)
    else:
        general_logger.error("Please provide an arXiv ID as a command line argument.")
        sys.exit(1)
