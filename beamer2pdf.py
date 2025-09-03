import sys
import logging
from core import compile_latex

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    if len(sys.argv) > 1:
        arxiv_id = sys.argv[1]
        tex_files_directory = f"source/{arxiv_id}/"
        if not compile_latex("slides.tex", tex_files_directory):
            sys.exit(1)
    else:
        logging.error("Please provide an arXiv ID as a command line argument.")
        sys.exit(1)
