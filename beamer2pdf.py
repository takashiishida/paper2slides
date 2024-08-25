import sys
import subprocess
import logging

def compile_latex(tex_file_path: str, output_directory: str) -> None:
    """
    Compiles a LaTeX file to PDF using pdflatex.
    """
    try:
        subprocess.run(["pdflatex", "-interaction=nonstopmode", tex_file_path], check=True, cwd=output_directory)
        logging.info(f"Successfully compiled {tex_file_path} using pdflatex.")
    except subprocess.CalledProcessError:
        logging.error("Failed to compile the LaTeX file. Check if pdflatex is installed and the .tex file is correct.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        arxiv_id = sys.argv[1]
        tex_files_directory = f"source/{arxiv_id}/"
        compile_latex("slides.tex", tex_files_directory)
    else:
        logging.error("Please provide an arXiv ID as a command line argument.")
        sys.exit(1)